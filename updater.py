import os
import re
import time
import requests
import json
from PySide6.QtCore import QThread, Signal
from config import CONFIG_FILE

# === НАЛАШТУВАННЯ ===
CURRENT_VERSION = "v1.0.1" 
GITHUB_REPO = "VPT-tech/VPT-MacroPad-Software" 
HEADERS = {
    "User-Agent": "VPT-MacroPad-App",
    "Accept": "application/vnd.github.v3+json"
}

def parse_version(v_str):
    """Коректно витягує тільки перші 3 числа (Major, Minor, Patch)"""
    nums = re.findall(r'\d+', str(v_str))
    if not nums:
        return (0, 0, 0)
    return tuple(map(int, (nums + ['0', '0', '0'])[:3]))

def get_latest_release_data():
    is_beta = False
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                is_beta = config.get("beta_tester", False)
    except Exception:
        pass

    try:
        if is_beta:
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
            resp = requests.get(api_url, headers=HEADERS, timeout=7)
            if resp.status_code == 200:
                releases = resp.json()
                if isinstance(releases, list) and len(releases) > 0:
                    return releases[0]
            return {}
        else:
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            resp = requests.get(api_url, headers=HEADERS, timeout=7)
            if resp.status_code == 200:
                return resp.json()
            return {}
    except Exception:
        return {}

class CheckUpdateThread(QThread):
    update_found_signal = Signal(str)

    def run(self):
        try:
            response = get_latest_release_data()
            if response and "tag_name" in response:
                latest_version = response["tag_name"]
                if parse_version(latest_version) > parse_version(CURRENT_VERSION):
                    self.update_found_signal.emit(latest_version)
        except Exception:
            pass 

class UpdaterThread(QThread):
    status_signal = Signal(str)
    update_ready_signal = Signal(str, str) 
    
    def run(self):
        try:
            self.status_signal.emit("Пошук оновлень...")
            response = get_latest_release_data()
            
            if not response or "tag_name" not in response:
                self.status_signal.emit("Сервер оновлень недоступний")
                return

            latest_version = response["tag_name"]
            self.status_signal.emit(f"Завантаження {latest_version}...")
            
            temp_dir = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "MacroPadUpdate")
            os.makedirs(temp_dir, exist_ok=True)
            
            unique_id = str(int(time.time()))
            exe_path = os.path.join(temp_dir, f"setup_{latest_version}_{unique_id}.exe")
            uf2_path = os.path.join(temp_dir, f"firmware_{latest_version}_{unique_id}.uf2")
            
            exe_downloaded = False
            uf2_downloaded = False

            for asset in response.get("assets", []):
                download_url = asset.get("browser_download_url", "")
                name = asset.get("name", "").lower()
                
                if name.endswith(".exe"):
                    if self.download_file(download_url, exe_path):
                        exe_downloaded = True
                elif name.endswith(".uf2"):
                    if self.download_file(download_url, uf2_path):
                        uf2_downloaded = True
            
            if exe_downloaded or uf2_downloaded:
                self.status_signal.emit("Готово до оновлення!")
                self.update_ready_signal.emit(
                    exe_path if exe_downloaded else "", 
                    uf2_path if uf2_downloaded else ""
                )
            else:
                self.status_signal.emit("Файли оновлення не знайдено")
            
        except Exception:
            self.status_signal.emit("Помилка завантаження.")

    def download_file(self, url, dest):
        try:
            r = requests.get(url, stream=True, headers=HEADERS, timeout=15)
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            return os.path.exists(dest) and os.path.getsize(dest) > 0
        except Exception:
            return False