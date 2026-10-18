from tkinter import messagebox
import customtkinter as ctk
import tkinter as tk
import os
import sys
import requests
import webbrowser
import zipfile
import shutil
import tempfile
import threading
import time
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION = "2.0"

# 自訂下拉式選單
class ScrollableComboBox(ctk.CTkFrame):
    def __init__(self, master, width=200, height=30, dropdown_height=150, **kwargs):
        super().__init__(master, **kwargs)
        self.values = []
        self.var = tk.StringVar(value="")

        self.entry = ctk.CTkEntry(self, textvariable=self.var, width=width, height=height, state="readonly",
                                  font=("微軟正黑體", 13))
        self.entry.pack(fill="x")

        self.btn = ctk.CTkButton(self, text="▼", width=30, height=height, command=self.toggle_dropdown,
                                 font=("微軟正黑體", 12, "bold"))
        self.btn.place(relx=1, rely=0, anchor="ne")

        self.dropdown_height = dropdown_height
        self.is_dropdown_open = False
        self.dropdown_window = None

    def toggle_dropdown(self):
        if self.is_dropdown_open:
            self.close_dropdown()
        else:
            self.open_dropdown()

    def open_dropdown(self):
        if self.dropdown_window:
            return
        self.dropdown_window = tk.Toplevel(self)
        self.dropdown_window.wm_overrideredirect(True)
        self.dropdown_window.wm_geometry("+%d+%d" % (self.winfo_rootx(), self.winfo_rooty() + self.winfo_height()))

        self.listbox = tk.Listbox(self.dropdown_window, height=10, font=("微軟正黑體", 12))
        self.listbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(self.dropdown_window, command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.listbox.delete(0, "end")
        for val in self.values:
            self.listbox.insert("end", val)

        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        self.dropdown_window.bind("<FocusOut>", lambda e: self.close_dropdown())

        self.is_dropdown_open = True
        self.dropdown_window.focus_set()

    def close_dropdown(self):
        if self.dropdown_window:
            self.dropdown_window.destroy()
            self.dropdown_window = None
        self.is_dropdown_open = False

    def on_select(self, event):
        selected_indices = self.listbox.curselection()
        if selected_indices:
            index = selected_indices[0]
            value = self.listbox.get(index)
            self.var.set(value)
            self.close_dropdown()

    def set(self, value):
        self.var.set(value)

    def get(self):
        return self.var.get()

    def configure_values(self, values):
        self.values = values
        if self.dropdown_window:
            self.listbox.delete(0, "end")
            for val in values:
                self.listbox.insert("end", val)

# 取得程式資源路徑
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# 顯示錯誤訊息
def show_error(title="錯誤", message="發生錯誤"):
    print(f"[ERROR] {title}: {message}")
    messagebox.showerror(title, message)

# 備援：用版本號碼本地推算 Java 版本（API 無法取得時使用）
def _fallback_java_version(mc_version):
    try:
        parts = mc_version.split(".")
        if mc_version.startswith("1.") and len(parts) > 1 and parts[1].isdigit():
            major = int(parts[1])
            minor = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        elif parts[0].isdigit():
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        else:
            return 8
        if major >= 26:
            return 25
        elif major >= 21 or (major == 20 and minor >= 5):
            return 21
        elif major >= 17:
            return 17
        else:
            return 8
    except Exception:
        return 8

# 取得 Paper 官方指定的 Java 最低需求版本 (來自 PaperMC fill API)
def get_paper_java_version(mc_version):
    try:
        url = f"https://fill.papermc.io/v3/projects/paper/versions/{mc_version}"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            java_min = data.get("version", {}).get("java", {}).get("version", {}).get("minimum")
            if java_min:
                return int(java_min)
    except Exception as e:
        print(f"[Paper Java版本取得失敗]: {e}")
    return None

# 取得 Mojang 官方指定的 Java 版本 (來自 Mojang version manifest)
def get_mojang_java_version(mc_version):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        manifest_resp = requests.get(
            "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
            headers=headers, timeout=5
        )
        if manifest_resp.status_code == 200:
            manifest_data = manifest_resp.json()
            version_info = next(
                (v for v in manifest_data.get("versions", []) if v["id"] == mc_version),
                None
            )
            if version_info and "url" in version_info:
                detail_resp = requests.get(version_info["url"], headers=headers, timeout=5)
                if detail_resp.status_code == 200:
                    detail_data = detail_resp.json()
                    java_major = detail_data.get("javaVersion", {}).get("majorVersion")
                    if java_major:
                        return int(java_major)
    except Exception as e:
        print(f"[Mojang Java版本取得失敗]: {e}")
    return None

# 透過 NeoForge POM 檔案精準解析對應的 Minecraft 版本
def get_neoforge_mc_version(neoforge_version):
    try:
        url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{neoforge_version}/neoforge-{neoforge_version}.pom"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            import re
            m = re.search(r'<artifactId>neoform</artifactId>\s*<version>([^<]+)', resp.text)
            if m:
                neoform_ver = m.group(1).split("-")[0]
                print(f"[NeoForge 解析] 版本 {neoforge_version} 對應 neoform 版本為 {neoform_ver}")
                return neoform_ver
    except Exception as e:
        print(f"[NeoForge MC版本解析失敗]: {e}")

    # 本地備援規則推算
    parts = neoforge_version.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        maj = int(parts[0])
        min_v = int(parts[1])
        if maj >= 26:
            return f"1.{maj}.{min_v}"
        elif maj >= 20:
            return f"1.{maj}.{min_v}"
        else:
            return f"1.{maj}"
    return neoforge_version

# 取得 NeoForge 官方指定的 Java 最低需求版本 (來自 NeoForge maven module 元資料)
def get_neoforge_java_version(version_str):
    try:
        url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version_str}/neoforge-{version_str}.module"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp.status_code == 200:
            mod = resp.json()
            jvm_vers = [
                v.get('attributes', {}).get('org.gradle.jvm.version')
                for v in mod.get('variants', [])
                if v.get('attributes', {}).get('org.gradle.jvm.version')
            ]
            if jvm_vers:
                return int(max(jvm_vers))
    except Exception as e:
        print(f"[NeoForge Java版本取得失敗]: {e}")
    return None

# 自動比對取得所需 Java 版本（依據伺服器類型對照 Paper/NeoForge 與 Mojang API，取最高者確保相容）
def get_required_java_version(version, server_type="Paper"):
    if server_type == "NeoForge":
        mc_version = get_neoforge_mc_version(version)
    else:
        mc_version = version

    mojang_ver = get_mojang_java_version(mc_version)
    paper_ver = get_paper_java_version(mc_version) if server_type == "Paper" else None
    neoforge_ver = get_neoforge_java_version(version) if server_type == "NeoForge" else None

    print(f"[Java版本對照] 版本: {version} ({server_type}, 對應MC: {mc_version}) | Mojang: {mojang_ver} | Paper: {paper_ver} | NeoForge: {neoforge_ver}")

    # Paper 伺服器
    if server_type == "Paper":
        if paper_ver and mojang_ver:
            chosen = max(paper_ver, mojang_ver)
            print(f"[Java版本] Paper 與 Mojang 對照後決定採用 Java {chosen}")
            return chosen
        elif paper_ver:
            return paper_ver
        elif mojang_ver:
            return mojang_ver

    # NeoForge 伺服器
    elif server_type == "NeoForge":
        if neoforge_ver and mojang_ver:
            chosen = max(neoforge_ver, mojang_ver)
            print(f"[Java版本] NeoForge 與 Mojang 對照後決定採用 Java {chosen}")
            return chosen
        elif neoforge_ver:
            return neoforge_ver
        elif mojang_ver:
            return mojang_ver

    # Vanilla 或其他伺服器
    elif mojang_ver:
        print(f"[Java版本] 採用 Mojang API 指定的 Java {mojang_ver}")
        return mojang_ver

    fallback_ver = _fallback_java_version(mc_version)
    print(f"[Java版本] API 查無結果，採用本地備援推算 Java {fallback_ver}")
    return fallback_ver


# 從 Adoptium API 取得 Java 下載連結
def get_adoptium_download_url(version):
    base = f"https://api.adoptium.net/v3/assets/latest/{version}/hotspot"
    params = {
        "architecture": "x64",
        "heap_size": "normal",
        "image_type": "jdk",
        "jvm_impl": "hotspot",
        "os": "windows",
        "vendor": "eclipse"
    }
    try:
        response = requests.get(base, params=params)
        response.raise_for_status()
        data = response.json()
        return data[0]["binary"]["package"]["link"]
    except Exception as e:
        show_error("Java下載失敗", f"取得下載網址時失敗：{e}")
        return None

# 自動下載 Java 並解壓縮、找出 java.exe
def download_java_with_progress(version, dest_folder, master, finish_callback):
    download_url = get_adoptium_download_url(version)
    if not download_url:
        finish_callback(None)
        return

    # 建立進度視窗
    progress_win = ctk.CTkToplevel(master)
    progress_win.configure(fg_color="#222222")
    progress_win.title("下載中...")
    progress_win.geometry("600x300")
    progress_win.resizable(False, False)
    progress_win.grab_set()

    label = ctk.CTkLabel(progress_win, text="正在下載 Java，請稍候...", font=("微軟正黑體", 14))
    label.pack(pady=(10, 10))

    progress_bar = ctk.CTkProgressBar(progress_win, width=350)
    progress_bar.pack(pady=(0, 10))
    progress_bar.set(0)

    temp_zip = os.path.join(tempfile.gettempdir(), f"java{version}.zip")

    def on_download_finish(java_path):
        progress_win.destroy()
        master.after(0, lambda: finish_callback(java_path))

    def download_task():
        java_path = None
        try:
            # 加入 retry 機制
            session = requests.Session()
            retries = requests.adapters.Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[502, 503, 504]
            )
            adapter = requests.adapters.HTTPAdapter(max_retries=retries)
            session.mount('https://', adapter)

            with session.get(download_url, stream=True) as r:
                r.raise_for_status()
                total_length = int(r.headers.get('content-length', 0))
                dl = 0
                start_time = time.time()
                last_update_time = time.time()

                with open(temp_zip, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=262144):  # 更大的 chunk
                        if chunk:
                            f.write(chunk)
                            dl += len(chunk)

                            # 節流進度條更新 (每0.05秒最多一次)
                            if total_length > 0:
                                now = time.time()
                                if now - last_update_time > 0.05:
                                    progress = dl / total_length
                                    progress_bar.set(progress)

                                    # 顯示速度（可省略）
                                    elapsed = now - start_time
                                    speed_kb = dl / 1024 / elapsed
                                    label.configure(text=f"正在下載 Java... {speed_kb:.1f} KB/s")
                                    last_update_time = now

            # 解壓縮
            extract_path = os.path.join(dest_folder, f"java{version}")
            if os.path.exists(extract_path):
                shutil.rmtree(extract_path)
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(extract_path)

            # 找到 java.exe 路徑
            for root, dirs, files in os.walk(extract_path):
                if "java.exe" in files:
                    java_path = os.path.join(root, "java.exe")
                    break

            if not java_path:
                show_error("Java未找到", "無法找到下載的 Java 執行檔")

        except Exception as e:
            show_error("Java下載失敗", f"錯誤: {e}")
            java_path = None
        finally:
            on_download_finish(java_path)

    threading.Thread(target=download_task, daemon=True).start()
# 取得可用的 Paper 版本列表
def get_paper_versions():
    try:
        response = requests.get("https://fill.papermc.io/v3/projects/paper", headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        data = response.json()
        versions = []
        for version_group in data.get("versions", {}).values():
            versions.extend(version_group)
        def version_key(v):
            parts = v.replace('-rc', '.rc').replace('-pre', '.pre').split('.')
            result = []
            for part in parts:
                if part.isdigit():
                    result.append(int(part))
                elif part.startswith('rc') and part[2:].isdigit():
                    result.append(-1)
                    result.append(int(part[2:]))
                elif part.startswith('pre') and part[3:].isdigit():
                    result.append(-2)
                    result.append(int(part[3:]))
                else:
                    result.append(part)
            return result
        versions.sort(key=version_key, reverse=True)
        return versions
    except Exception as e:
        show_error("版本取得失敗", f"抓取 Paper 版本資訊時發生錯誤：{e}")
        return []

# 取得可用的 Vanilla 版本列表
def get_vanilla_versions():
    try:
        response = requests.get("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json", headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        data = response.json()
        versions = [v["id"] for v in data.get("versions", []) if v.get("type") == "release"]
        def version_key(v):
            parts = v.replace('-rc', '.rc').replace('-pre', '.pre').split('.')
            result = []
            for part in parts:
                if part.isdigit():
                    result.append(int(part))
                elif part.startswith('rc') and part[2:].isdigit():
                    result.append(-1)
                    result.append(int(part[2:]))
                elif part.startswith('pre') and part[3:].isdigit():
                    result.append(-2)
                    result.append(int(part[3:]))
                else:
                    result.append(part)
            return result
        versions.sort(key=version_key, reverse=True)
        return versions
    except Exception as e:
        show_error("版本取得失敗", f"抓取 Vanilla 版本資訊時發生錯誤：{e}")
        return []

# 取得可用的 NeoForge 版本列表
def get_neoforge_versions():
    try:
        response = requests.get("https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml", headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.text)
        versions = []
        for version_elem in root.findall(".//version"):
            version = version_elem.text
            if version and not version.endswith("-SNAPSHOT"):
                versions.append(version)
        def version_key(v):
            parts = v.replace('-rc', '.rc').replace('-pre', '.pre').split('.')
            result = []
            for part in parts:
                if part.isdigit():
                    result.append(int(part))
                elif part.startswith('rc') and part[2:].isdigit():
                    result.append(-1)
                    result.append(int(part[2:]))
                elif part.startswith('pre') and part[3:].isdigit():
                    result.append(-2)
                    result.append(int(part[3:]))
                else:
                    result.append(part)
            return result
        versions.sort(key=version_key, reverse=True)
        return versions
    except Exception as e:
        show_error("版本取得失敗", f"抓取 NeoForge 版本資訊時發生錯誤：{e}")
        return []

# 取得可用的 Forge 版本列表 (Minecraft 支援版本)
def get_forge_versions():
    try:
        response = requests.get("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        response.raise_for_status()
        promos = response.json().get("promos", {})
        mc_set = set()
        for k in promos.keys():
            mc_v = k.replace("-latest", "").replace("-recommended", "")
            if mc_v:
                mc_set.add(mc_v)

        def version_key(v):
            parts = v.split(".")
            result = []
            for p in parts:
                if p.isdigit():
                    result.append(int(p))
                else:
                    result.append(p)
            return result

        versions = sorted(list(mc_set), key=version_key, reverse=True)
        return versions
    except Exception as e:
        show_error("版本取得失敗", f"抓取 Forge 版本資訊時發生錯誤：{e}")
        return []

# 取得 Forge 伺服器安裝檔 (installer.jar) 下載連結
def get_forge_server_url(mc_version):
    try:
        response = requests.get("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        response.raise_for_status()
        promos = response.json().get("promos", {})
        forge_build = promos.get(f"{mc_version}-recommended") or promos.get(f"{mc_version}-latest")
        if not forge_build:
            return None
        full_ver = f"{mc_version}-{forge_build}"
        return f"https://maven.minecraftforge.net/net/minecraftforge/forge/{full_ver}/forge-{full_ver}-installer.jar"
    except Exception as e:
        print(f"[Forge 下載連結解析失敗]: {e}")
        return None

# 取得可用的 Fabric 版本列表
def get_fabric_versions():
    try:
        response = requests.get("https://meta.fabricmc.net/v2/versions/game", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        response.raise_for_status()
        games = response.json()
        versions = [g["version"] for g in games if g.get("stable")]
        return versions
    except Exception as e:
        show_error("版本取得失敗", f"抓取 Fabric 版本資訊時發生錯誤：{e}")
        return []

# 取得 Fabric 伺服器 jar (包含 installer 與 loader) 下載連結
def get_fabric_server_url(mc_version):
    try:
        # 取得最新 loader 與 installer 版本
        loader_resp = requests.get(f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        loader_resp.raise_for_status()
        loader_list = loader_resp.json()
        if not loader_list:
            return None
        loader_ver = loader_list[0]["loader"]["version"]

        inst_resp = requests.get("https://meta.fabricmc.net/v2/versions/installer", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        inst_resp.raise_for_status()
        installer_ver = inst_resp.json()[0]["version"]

        return f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}/{loader_ver}/{installer_ver}/server/jar"
    except Exception as e:
        print(f"[Fabric 下載連結解析失敗]: {e}")
        return None

# 取得 NeoForge 伺服器安裝檔 (installer.jar) 下載連結
def get_neoforge_server_url(neoforge_version):
    return f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{neoforge_version}/neoforge-{neoforge_version}-installer.jar"

# 寫入 eula.txt
def create_or_update_eula_file(agree: bool, folder_path: str):
    if not folder_path:
        return
    try:
        eula_path = os.path.join(folder_path, "eula.txt")
        with open(eula_path, "w", encoding="utf-8") as f:
            f.write(f"eula={'true' if agree else 'false'}\n")
    except Exception as e:
        show_error("EULA 檔案錯誤", f"寫入 EULA 檔案失敗：{e}")

# 建立 start.bat 啟動腳本 (支援 NeoForge 與標準 server.jar)
def create_start_bat(folder_path, min_memory, max_memory, use_gui, java_path=None, server_type="Paper"):
    if not folder_path:
        show_error("安裝路徑錯誤", "請先選擇安裝路徑")
        return
    try:
        if server_type in ("NeoForge", "Forge"):
            # NeoForge / Forge: 將記憶體設定寫入 user_jvm_args.txt
            user_args_path = os.path.join(folder_path, "user_jvm_args.txt")
            user_args_content = f"-Xms{min_memory}M\n-Xmx{max_memory}M\n"
            try:
                with open(user_args_path, "w", encoding="utf-8") as f:
                    f.write(user_args_content)
            except Exception as e:
                print(f"[user_jvm_args.txt 寫入警告]: {e}")

            # 檢查 run.bat 是否存在，如果自訂了 Java 路徑，則更新 run.bat 中的 java 調用
            run_bat_path = os.path.join(folder_path, "run.bat")
            if os.path.exists(run_bat_path) and java_path:
                try:
                    import re
                    clean_java_path = os.path.normpath(java_path)
                    with open(run_bat_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    with open(run_bat_path, "w", encoding="utf-8") as f:
                        for line in lines:
                            # 嚴格匹配行首的 java 命令 (忽略前面可能的空格)，避免誤傷註解
                            if re.match(r'^\s*java\s+@', line):
                                updated_line = re.sub(r'^\s*java\b', f'"{clean_java_path}"', line)
                                f.write(updated_line)
                            else:
                                f.write(line)
                except Exception as e:
                    print(f"[run.bat 調整警告]: {e}")

            # 判斷是新版 run.bat 還是舊版 forge.jar
            bat_path = os.path.join(folder_path, "start.bat")
            if os.path.exists(run_bat_path):
                with open(bat_path, "w", encoding="utf-8") as f:
                    f.write("@echo off\n")
                    if use_gui:
                        f.write("call run.bat\n")
                    else:
                        f.write("call run.bat nogui\n")
                    f.write("pause\n")
            else:
                # 舊版 Forge (1.16.5 以前) 直接以 jar 啟動
                forge_jars = [fn for fn in os.listdir(folder_path) if fn.startswith("forge-") and fn.endswith(".jar") and not fn.endswith("-installer.jar")]
                target_jar = forge_jars[0] if forge_jars else "server.jar"
                with open(bat_path, "w", encoding="utf-8") as f:
                    f.write("@echo off\n")
                    f.write(f'"{java_path if java_path else "java"}" -Xms{min_memory}M -Xmx{max_memory}M ')
                    f.write("-Dnogui=false " if use_gui else "-Dnogui=true ")
                    f.write(f"-jar {target_jar}\n" if use_gui else f"-jar {target_jar} nogui\n")
                    f.write("pause\n")

            print(f"成功建立 {server_type} 啟動腳本於 {bat_path}")

        else:
            bat_path = os.path.join(folder_path, "start.bat")
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write("@echo off\n")
                f.write(f'"{java_path if java_path else "java"}" -Xms{min_memory}M -Xmx{max_memory}M ')
                f.write("-Dnogui=false " if use_gui else "-Dnogui=true ")
                f.write("-jar server.jar\n" if use_gui else "-jar server.jar nogui\n")
                f.write("pause\n")
            print(f"成功建立 start.bat 檔案於 {bat_path}")
    except Exception as e:
        show_error("start.bat 錯誤", f"寫入 start.bat 失敗：{e}")

# 下載伺服器 jar 檔（帶進度條的非同步版本，支援 NeoForge 自動 --installServer 安裝）
def download_server_jar_with_progress(folder_path, version, server_type, master, finish_callback, java_path=None):
    if not folder_path or not version:
        show_error("下載失敗", "請先選擇安裝路徑和版本")
        finish_callback(False)
        return

    # 建立進度視窗
    progress_win = ctk.CTkToplevel(master)
    progress_win.configure(fg_color="#222222")
    progress_win.title("下載伺服器中...")
    progress_win.geometry("600x300")
    progress_win.resizable(False, False)
    progress_win.grab_set()

    label = ctk.CTkLabel(progress_win, text=f"正在取得 {server_type} {version} 下載資訊...", font=("微軟正黑體", 14))
    label.pack(pady=(30, 10))

    progress_bar = ctk.CTkProgressBar(progress_win, width=400)
    progress_bar.pack(pady=(0, 10))
    progress_bar.set(0)

    speed_label = ctk.CTkLabel(progress_win, text="", font=("微軟正黑體", 12))
    speed_label.pack(pady=(0, 10))

    def on_finish(success):
        progress_win.destroy()
        master.after(0, lambda: finish_callback(success))

    def download_task():
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            jar_url = None

            if server_type == "Paper":
                builds_url = f"https://fill.papermc.io/v3/projects/paper/versions/{version}/builds"
                builds_response = requests.get(builds_url, headers=headers)
                builds_response.raise_for_status()
                builds_data = builds_response.json()

                stable_build = None
                for build in builds_data:
                    if build.get("channel") == "STABLE":
                        stable_build = build
                        break

                if not stable_build:
                    show_error("下載錯誤", f"找不到 {version} 的穩定版本建置")
                    on_finish(False)
                    return

                download_info = stable_build.get("downloads", {}).get("server:default", {})
                jar_url = download_info.get("url")
                if not jar_url:
                    show_error("下載錯誤", f"無法取得 {version} 的下載連結")
                    on_finish(False)
                    return

            elif server_type == "Vanilla":
                manifest_url = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
                manifest_response = requests.get(manifest_url, headers=headers)
                manifest_response.raise_for_status()
                manifest_data = manifest_response.json()

                version_info = None
                for v in manifest_data.get("versions", []):
                    if v["id"] == version:
                        version_info = v
                        break

                if not version_info:
                    show_error("下載錯誤", f"找不到 {version} 的版本資訊")
                    on_finish(False)
                    return

                version_detail_url = version_info["url"]
                detail_response = requests.get(version_detail_url, headers=headers)
                detail_response.raise_for_status()
                detail_data = detail_response.json()

                jar_url = detail_data.get("downloads", {}).get("server", {}).get("url")
                if not jar_url:
                    show_error("下載錯誤", f"無法取得 {version} 的 Vanilla 伺服器下載連結")
                    on_finish(False)
                    return

            elif server_type == "NeoForge":
                jar_url = get_neoforge_server_url(version)
                if not jar_url:
                    show_error("下載錯誤", f"無法取得 NeoForge {version} 的安裝檔下載連結")
                    on_finish(False)
                    return

            elif server_type == "Forge":
                jar_url = get_forge_server_url(version)
                if not jar_url:
                    show_error("下載錯誤", f"無法取得 Forge {version} 的安裝檔下載連結")
                    on_finish(False)
                    return

            elif server_type == "Fabric":
                jar_url = get_fabric_server_url(version)
                if not jar_url:
                    show_error("下載錯誤", f"無法取得 Fabric {version} 的伺服器下載連結")
                    on_finish(False)
                    return

            else:
                show_error("下載錯誤", f"不支援的伺服器類型: {server_type}")
                on_finish(False)
                return

            # 開始串流下載
            label.configure(text=f"正在下載 {server_type} {version} 伺服器檔案...")
            if server_type in ("NeoForge", "Forge"):
                target_file_name = "installer.jar"
            else:
                target_file_name = "server.jar"

            jar_path = os.path.join(folder_path, target_file_name)
            
            session = requests.Session()
            retries = requests.adapters.Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[502, 503, 504]
            )
            adapter = requests.adapters.HTTPAdapter(max_retries=retries)
            session.mount('https://', adapter)

            with session.get(jar_url, headers=headers, stream=True) as r:
                r.raise_for_status()
                total_length = int(r.headers.get('content-length', 0))
                dl = 0
                start_time = time.time()
                last_update_time = time.time()

                with open(jar_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=262144):
                        if chunk:
                            f.write(chunk)
                            dl += len(chunk)

                            now = time.time()
                            if now - last_update_time > 0.05:
                                if total_length > 0:
                                    progress = dl / total_length
                                    progress_bar.set(progress)
                                elapsed = now - start_time
                                speed_kb = dl / 1024 / elapsed if elapsed > 0 else 0
                                downloaded_mb = dl / 1024 / 1024
                                total_mb = total_length / 1024 / 1024 if total_length > 0 else 0
                                if total_length > 0:
                                    speed_label.configure(text=f"{downloaded_mb:.1f} MB / {total_mb:.1f} MB  |  {speed_kb:.1f} KB/s")
                                else:
                                    speed_label.configure(text=f"{downloaded_mb:.1f} MB 已下載  |  {speed_kb:.1f} KB/s")
                                last_update_time = now

            print(f"成功下載 {server_type} {version} 檔案至 {jar_path}")

            # 若為 NeoForge 或 Forge，需在下載完成後執行 installer.jar --installServer 產生伺服器核心與函式庫
            if server_type in ("NeoForge", "Forge"):
                label.configure(text=f"正在安裝 {server_type} 伺服器函式庫與核心 (請稍候)...")
                speed_label.configure(text="正在執行 --installServer，這可能需要一至兩分鐘...")
                progress_bar.configure(mode="indeterminate")
                progress_bar.start()

                import subprocess
                cmd_java = java_path if java_path else "java"
                install_cmd = [cmd_java, "-jar", "installer.jar", "--installServer"]

                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NO_WINDOW

                print(f"[{server_type} 安裝] 執行命令: {' '.join(install_cmd)} 在 {folder_path}")
                res = subprocess.run(
                    install_cmd,
                    cwd=folder_path,
                    capture_output=True,
                    text=True,
                    creationflags=creation_flags
                )

                if res.returncode != 0:
                    err_msg = res.stderr or res.stdout or "未知錯誤"
                    print(f"[{server_type} 安裝失敗]: {err_msg}")
                    show_error(f"{server_type} 安裝失敗", f"執行 installer 安裝失敗：\n{err_msg[:500]}")
                    on_finish(False)
                    return

                print(f"[{server_type} 安裝成功] 完成函式庫與啟動腳本建立")

            on_finish(True)

        except Exception as e:
            show_error("下載錯誤", f"錯誤訊息：{e}")
            on_finish(False)

    threading.Thread(target=download_task, daemon=True).start()

# 建立 server.properties 設定檔
def create_server_properties(folder_path, online_mode, max_players, pvp, server_port):
    if not folder_path:
        return
    try:
        props_path = os.path.join(folder_path, "server.properties")
        with open(props_path, "w", encoding="utf-8") as f:
            f.write(f"online-mode={'true' if online_mode == '啟用' else 'false'}\n")
            f.write(f"max-players={max_players}\n")
            f.write(f"pvp={'true' if pvp == '啟用' else 'false'}\n")
            f.write(f"server-port={server_port}\n")
        print("server.properties 寫入完成")
    except Exception as e:
        show_error("server.properties 錯誤", f"寫入失敗：{e}")

# 開啟 EULA 網頁連結
def open_eula_link(event=None):
    webbrowser.open("https://account.mojang.com/documents/minecraft_eula")


# GUI 主體與元件建構
def CreateGUI():
    global version_dropdown, InstallPathEntry, eula_var, MinMemory_var, MaxMemory_var, ServerGUI_var, Download_Java_CheckBox_var
    global OnlineMode_ComboBox, MaxPlayers_var, PVP_ComboBox, port_var, status_var, server_type_var

    win = ctk.CTk()
    win.title(f"Minecraft 伺服器架設工具 v{APP_VERSION}")
    win.geometry("550x640")
    win.resizable(False, False)

    icon_path = resource_path('GUI_icon.ico')
    try:
        win.iconbitmap(icon_path)
    except:
        pass

    tabview = ctk.CTkTabview(win)
    tabview.pack(expand=True, fill="both", padx=20, pady=20)
    tabview.add("基本設定")
    tabview.add("進階設定")
    tabview.add("關於我們")
    basic_tab = tabview.tab("基本設定")
    advanced_tab = tabview.tab("進階設定")
    about_tab = tabview.tab("關於我們")

    # 基本設定 Tab 元件
    label_type = ctk.CTkLabel(basic_tab, text="伺服器類型:", font=('微軟正黑體', 15, 'bold'))
    label_type.grid(row=0, column=0, padx=(20, 10), pady=20, sticky="w")

    server_type_var = tk.StringVar(value="Paper")
    server_type_dropdown = ctk.CTkOptionMenu(
        basic_tab,
        width=150,
        height=30,
        values=["Paper", "Vanilla", "NeoForge", "Forge", "Fabric"],
        variable=server_type_var,
        font=('微軟正黑體', 13)
    )
    server_type_dropdown.grid(row=0, column=1, padx=(0, 20), pady=20, sticky="ew")

    label_version = ctk.CTkLabel(basic_tab, text="遊戲版本:", font=('微軟正黑體', 15, 'bold'))
    label_version.grid(row=2, column=0, padx=(20, 10), pady=20, sticky="w")

    version_dropdown = ScrollableComboBox(basic_tab)
    version_dropdown.grid(row=2, column=1, padx=(0, 20), pady=20, sticky="ew")

    def update_versions(*args):
        server_type = server_type_var.get()
        if server_type == "Paper":
            versions = get_paper_versions()
        elif server_type == "Vanilla":
            versions = get_vanilla_versions()
        elif server_type == "NeoForge":
            versions = get_neoforge_versions()
        elif server_type == "Forge":
            versions = get_forge_versions()
        elif server_type == "Fabric":
            versions = get_fabric_versions()
        else:
            versions = []
        version_dropdown.configure_values(versions)
        version_dropdown.set("請選擇版本")

    server_type_var.trace_add("write", update_versions)
    update_versions()

    label_path = ctk.CTkLabel(basic_tab, text="安裝位置:", font=('微軟正黑體', 15, 'bold'))
    label_path.grid(row=3, column=0, padx=(20, 10), pady=10, sticky="w")

    path_frame = ctk.CTkFrame(basic_tab)
    path_frame.grid(row=3, column=1, padx=(0, 20), pady=10, sticky="ew")
    path_frame.grid_columnconfigure(0, weight=1)

    InstallPathEntry = ctk.CTkEntry(path_frame, height=30, font=("微軟正黑體", 13))
    InstallPathEntry.grid(row=0, column=0, sticky="ew")

    def select_folder():
        folder = ctk.filedialog.askdirectory()
        if folder:
            InstallPathEntry.delete(0, "end")
            InstallPathEntry.insert(0, folder)

    btn_browse = ctk.CTkButton(path_frame, text="📁", width=30, command=select_folder, font=("微軟正黑體", 14, "bold"))
    btn_browse.grid(row=0, column=1)

    eula_var = tk.BooleanVar(value=False)
    label_eula = ctk.CTkLabel(basic_tab, text="EULA條款:", font=('微軟正黑體', 15, 'bold'))
    label_eula.grid(row=4, column=0, padx=(20, 10), pady=(10, 20), sticky="w")

    eula_checkbox = ctk.CTkCheckBox(basic_tab, text="我同意EULA條款", variable=eula_var, font=('微軟正黑體', 15, 'bold'))
    eula_checkbox.grid(row=4, column=1, padx=20, pady=(10, 20), sticky="w")

    eula_label = ctk.CTkLabel(basic_tab, text="查看EULA", text_color="yellow", font=("微軟正黑體", 13, "underline"), cursor="hand2")
    eula_label.grid(row=4, column=2, sticky="w", padx=(10, 10), pady=(10, 20))
    eula_label.bind("<Button-1>", open_eula_link)

    ServerGUI_var = tk.BooleanVar(value=False)
    ServerGUI_label = ctk.CTkLabel(basic_tab, text="GUI介面:", font=('微軟正黑體', 15, 'bold'))
    ServerGUI_label.grid(row=5, column=0, padx=(20, 10), pady=(10, 20), sticky="w")

    ServerGUI_checkbox = ctk.CTkCheckBox(basic_tab, text="啟用伺服器GUI介面", variable=ServerGUI_var, font=('微軟正黑體', 15, 'bold'))
    ServerGUI_checkbox.grid(row=5, column=1, padx=(20, 20), pady=(10, 20), sticky="w")

    Download_Java_CheckBox_var = tk.BooleanVar(value=False)
    Download_Java_CheckBox = ctk.CTkCheckBox(basic_tab, text="自動下載所需Java", variable=Download_Java_CheckBox_var, font=('微軟正黑體', 15, 'bold'))
    Download_Java_CheckBox.grid(row=6, column=1, padx=(20, 20), pady=(10, 20), sticky="w")

    MinMemory_var = tk.IntVar(value=1024)
    MaxMemory_var = tk.IntVar(value=4096)

    Memory_Label = ctk.CTkLabel(basic_tab, text="記憶體分配:", font=('微軟正黑體', 15, 'bold'), text_color="SkyBlue")
    Memory_Label.grid(row=7, column=0, padx=(20, 10), pady=(10, 20), sticky="w")

    MinMemory_Label = ctk.CTkLabel(basic_tab, text="最小記憶體 (MB):", font=('微軟正黑體', 13))
    MinMemory_Label.grid(row=8, column=0, padx=(20, 10), pady=(5, 5), sticky="w")
    MinMemory_Slider = ctk.CTkSlider(basic_tab, from_=1024, to=8192, variable=MinMemory_var, number_of_steps=16)
    MinMemory_Slider.grid(row=8, column=1, padx=(0, 20), pady=(5, 5), sticky="ew")

    MaxMemory_Label = ctk.CTkLabel(basic_tab, text="最大記憶體 (MB):", font=('微軟正黑體', 13))
    MaxMemory_Label.grid(row=9, column=0, padx=(20, 10), pady=(5, 20), sticky="w")
    MaxMemory_Slider = ctk.CTkSlider(basic_tab, from_=2048, to=8192, variable=MaxMemory_var, number_of_steps=32)
    MaxMemory_Slider.grid(row=9, column=1, padx=(0, 20), pady=(5, 20), sticky="ew")

    MinMemory_Display = tk.StringVar()
    MaxMemory_Display = tk.StringVar()

    def update_memory_display(*args):
        MinMemory_Display.set(f"{MinMemory_var.get()} MB")
        MaxMemory_Display.set(f"{MaxMemory_var.get()} MB")

    MinMemory_var.trace_add("write", update_memory_display)
    MaxMemory_var.trace_add("write", update_memory_display)
    update_memory_display()

    MinMemory_Text = ctk.CTkLabel(basic_tab, textvariable=MinMemory_Display, font=('微軟正黑體', 13))
    MinMemory_Text.grid(row=8, column=2, padx=(10, 20), pady=(5, 5), sticky="w")
    MaxMemory_Text = ctk.CTkLabel(basic_tab, textvariable=MaxMemory_Display, font=('微軟正黑體', 13))
    MaxMemory_Text.grid(row=9, column=2, padx=(10, 20), pady=(5, 20), sticky="w")

    # 狀態欄
    status_var = tk.StringVar(value="已就緒")
    StateText = ctk.CTkLabel(basic_tab, textvariable=status_var, font=('微軟正黑體', 17, 'bold'), text_color="#02F78E")
    StateText.grid(row=10, column=0, columnspan=3, padx=(20, 10), pady=(10, 20), sticky="w")

    # 進階設定 Tab 元件
    OnlineMode_var = tk.StringVar(value="啟用")
    OnlineMode_Label = ctk.CTkLabel(advanced_tab, text="正版驗證:\n(Online-Mode)", font=('微軟正黑體', 13, 'bold'), justify="left", anchor="w")
    OnlineMode_Label.grid(row=0, column=0, padx=(20, 10), pady=(10, 20), sticky="w")
    OnlineMode_ComboBox = ctk.CTkOptionMenu(advanced_tab, width=150, height=30, values=["啟用", "停用"], font=('微軟正黑體', 13))
    OnlineMode_ComboBox.grid(row=0, column=1, padx=(0, 20), pady=(10, 20), sticky="ew")
    OnlineMode_ComboBox.set("啟用")

    MaxPlayers_var = tk.IntVar(value=10)
    MaxPlayers_Label = ctk.CTkLabel(advanced_tab, text="玩家數量上限:\n(Max-Player)", font=('微軟正黑體', 13, 'bold'), justify="left", anchor="w")
    MaxPlayers_Label.grid(row=1, column=0, padx=(20, 10), pady=(10, 20), sticky="w")
    MaxPlayers_Entry = ctk.CTkEntry(advanced_tab, textvariable=MaxPlayers_var, width=100, height=30, font=("微軟正黑體", 13))
    MaxPlayers_Entry.grid(row=1, column=1, padx=(0, 20), pady=(10, 20), sticky="ew")

    PVP_var = tk.StringVar(value="啟用")
    PVP_label = ctk.CTkLabel(advanced_tab, text="玩家間傷害:\n(PVP)", font=('微軟正黑體', 13, 'bold'), justify="left", anchor="w")
    PVP_label.grid(row=3, column=0, padx=(20, 10), pady=(10, 20), sticky="w")
    PVP_ComboBox = ctk.CTkOptionMenu(advanced_tab, width=150, height=30, values=["啟用", "停用"], font=('微軟正黑體', 13))
    PVP_ComboBox.grid(row=3, column=1, padx=(0, 20), pady=(10, 20), sticky="ew")
    PVP_ComboBox.set("啟用")

    port_var = tk.IntVar(value=25565)
    Port_Label = ctk.CTkLabel(advanced_tab, text="伺服器連接埠:\n(Server Port)", font=('微軟正黑體', 13, 'bold'), justify="left", anchor="w")
    Port_Label.grid(row=4, column=0, padx=(20, 10), pady=(10, 20), sticky="w")
    Port_Entry = ctk.CTkEntry(advanced_tab, textvariable=port_var, width=100, height=30)
    Port_Entry.grid(row=4, column=1, padx=(0, 20), pady=(10, 20), sticky="ew")

    # 關於我們 Tab 元件 (表格版)
    about_label_title = ctk.CTkLabel(
        about_tab,
        text="Minecraft 伺服器架設工具",
        font=('微軟正黑體', 18, 'bold'),
        anchor="w"
    )
    about_label_title.grid(row=0, column=0, sticky="w", padx=20, pady=(20, 5))

    about_label_version = ctk.CTkLabel(
        about_tab,
        text=f"版本：{APP_VERSION}",
        font=('微軟正黑體', 15),
        anchor="w"
    )
    about_label_version.grid(row=1, column=0, sticky="w", padx=20, pady=5)

    about_label_author = ctk.CTkLabel(
        about_tab,
        text="原作者：Even小饅頭",
        font=('微軟正黑體', 15),
        anchor="w"
    )
    about_label_author.grid(row=2, column=0, sticky="w", padx=20, pady=5)

    # 分隔線
    separator = ctk.CTkFrame(about_tab, height=2, fg_color="#444444")
    separator.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 10))

    # 貢獻者名單標題
    about_label_contributors_title = ctk.CTkLabel(
        about_tab,
        text="貢獻者名單：",
        font=('微軟正黑體', 16, 'bold'),
        anchor="w"
    )
    about_label_contributors_title.grid(row=4, column=0, sticky="w", padx=20, pady=(5, 2))

    # 貢獻者列表 (名稱, 連結，如果沒有連結就 None)
    contributors = [
        ("SalmonSkate2256", "https://www.youtube.com/@SalmonSkate2256大帳/"),
        ("以下內容歡迎各位貢獻者加入！", None),
    ]

    # 顯示貢獻者
    for idx, (name, link) in enumerate(contributors, start=5):
        if link:  # 有連結 → 可點擊
            lbl = ctk.CTkLabel(
                about_tab,
                text=name,
                font=('微軟正黑體', 14, 'underline'),
                text_color="skyblue",
                cursor="hand2",
                anchor="w"
            )
            lbl.bind("<Button-1>", lambda e, url=link: webbrowser.open_new(url))
        else:  # 沒連結 → 純文字
            lbl = ctk.CTkLabel(
                about_tab,
                text=name,
                font=('微軟正黑體', 14),
                anchor="w"
            )
        lbl.grid(row=idx, column=0, sticky="w", padx=40, pady=2)

    # 開始佈署按鈕
    CreateServerButton = ctk.CTkButton(basic_tab, text='開始佈署', width=50, height=20, font=('微軟正黑體', 15, 'bold'))
    CreateServerButton.grid(row=10, column=2, columnspan=3, padx=(20, 20), pady=(5, 5), sticky="ew")

    return win, CreateServerButton, status_var
def on_create_server():
    # 先取得所有設定值
    folder = InstallPathEntry.get().strip()
    version = version_dropdown.get()
    agree_eula = eula_var.get()
    min_mem = MinMemory_var.get()
    max_mem = MaxMemory_var.get()
    use_gui = ServerGUI_var.get()

    online_mode = OnlineMode_ComboBox.get()
    max_players = MaxPlayers_var.get()
    pvp = PVP_ComboBox.get()
    server_port = port_var.get()

    # 檢查必填欄位
    if not folder:
        messagebox.showwarning("警告", "請選擇伺服器安裝路徑")
        return
    if version == "請選擇版本":
        messagebox.showwarning("警告", "請選擇遊戲版本")
        return
    if not agree_eula:
        messagebox.showwarning("警告", "請同意 EULA 條款")
        return
    if min_mem > max_mem:
        messagebox.showwarning("警告", "最小記憶體不得大於最大記憶體")
        return

    # 更新狀態欄
    status_var.set("開始架設伺服器中...")

    # 定義架設完成後的行為
    def setup_finished(success, msg=None):
        if success:
            status_var.set("伺服器架設完成！")
            messagebox.showinfo("成功", "伺服器設定完成！")
        else:
            status_var.set("伺服器架設失敗")
            if msg:
                messagebox.showerror("錯誤", msg)

    # 進行伺服器建立流程
    def continue_setup(java_path):
        try:
            server_type = server_type_var.get()
            create_or_update_eula_file(agree_eula, folder)
            status_var.set("正在下載並準備伺服器核心檔案...")

            def on_jar_downloaded(success):
                if success:
                    try:
                        create_start_bat(folder, min_mem, max_mem, use_gui, java_path, server_type)
                        create_server_properties(folder, online_mode, max_players, pvp, server_port)
                        setup_finished(True)
                    except Exception as e:
                        setup_finished(False, f"建立伺服器設定時發生錯誤：{e}")
                else:
                    setup_finished(False, "伺服器核心下載或安裝失敗，無法繼續架設")

            download_server_jar_with_progress(folder, version, server_type, win, on_jar_downloaded, java_path)
        except Exception as e:
            setup_finished(False, f"建立伺服器時發生錯誤：{e}")

    # 如果需要下載 Java，先下載 Java 再繼續架設
    if Download_Java_CheckBox_var.get():
        server_type = server_type_var.get()
        required_java = get_required_java_version(version, server_type)
        status_var.set(f"開始下載 Java {required_java}...")

        def on_java_download_finished(java_path):
            if java_path:
                status_var.set("Java 下載完成，繼續架設伺服器")
                continue_setup(java_path)
            else:
                status_var.set("Java 下載失敗")
                messagebox.showerror("錯誤", "Java 下載失敗，無法繼續架設")

        # 這邊呼叫你自訂的下載函式，需要支援 callback
        download_java_with_progress(required_java, folder, win, on_java_download_finished)

    else:
        # 不下載 Java，直接架設
        continue_setup(None)


# 最後，綁定開始佈署按鈕事件（假設你已經從 CreateGUI() 拿到按鈕）
win, CreateServerButton, status_var = CreateGUI()
CreateServerButton.configure(command=on_create_server)
win.mainloop()
