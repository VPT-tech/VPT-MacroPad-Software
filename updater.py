import os
import re
import hmac
import time
import hashlib
import threading
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

# ---------------------------------------------------------------- цілісність оновлень
# Інсталятор запускається з правами адміністратора, тож кожен файл перевіряється за SHA-256:
# GitHub сам рахує дайджест для кожного asset (поле "digest": "sha256:..."), запасний
# варіант — файл SHA256SUMS / checksums.txt / <ім'я>.sha256 у тому ж релізі.
# Без контрольної суми файл НЕ встановлюється.
_CHECKSUM_FILE_NAMES = ("sha256sums", "sha256sums.txt", "checksums.txt", "checksums.sha256")
_VERIFIED = {}
_VERIFIED_LOCK = threading.Lock()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def parse_checksums(text):
    """Формат sha256sum: '<64 hex>  <ім'я файлу>' (або з '*' перед ім'ям)."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[os.path.basename(m.group(2).strip()).lower()] = m.group(1).lower()
    return out


def expected_sha256_for_asset(asset, checksums=None):
    digest = asset.get("digest") or ""
    if isinstance(digest, str) and digest.lower().startswith("sha256:"):
        hexd = digest.split(":", 1)[1].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", hexd):
            return hexd
    if checksums:
        return checksums.get((asset.get("name") or "").lower())
    return None


def verify_file(path, expected_sha, expected_size=None):
    if not expected_sha or not path or not os.path.isfile(path):
        return False
    if expected_size is not None and os.path.getsize(path) != expected_size:
        return False
    return hmac.compare_digest(sha256_file(path), expected_sha.lower())


def register_verified(path, sha):
    with _VERIFIED_LOCK:
        _VERIFIED[os.path.abspath(path)] = sha.lower()


def expected_sha256_for_path(path):
    with _VERIFIED_LOCK:
        return _VERIFIED.get(os.path.abspath(path)) if path else None


def is_verified(path):
    """Повторна перевірка безпосередньо перед запуском: файл у %TEMP% міг бути
    підмінений іншим процесом між завантаженням і підтвердженням UAC."""
    exp = expected_sha256_for_path(path)
    return bool(exp) and verify_file(path, exp)


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

            safe_ver = re.sub(r"[^0-9A-Za-z._-]", "_", str(latest_version))
            unique_id = str(int(time.time()))
            exe_path = os.path.join(temp_dir, f"setup_{safe_ver}_{unique_id}.exe")
            uf2_path = os.path.join(temp_dir, f"firmware_{safe_ver}_{unique_id}.uf2")

            assets = [a for a in response.get("assets", []) if isinstance(a, dict)]
            checksums = self.fetch_checksums(assets)

            exe_downloaded = False
            uf2_downloaded = False
            integrity_error = False

            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".exe") and not exe_downloaded:
                    target = exe_path
                elif name.endswith(".uf2") and not uf2_downloaded:
                    target = uf2_path
                else:
                    continue
                expected = expected_sha256_for_asset(asset, checksums)
                if not expected:
                    integrity_error = True
                    continue
                size = asset.get("size") if isinstance(asset.get("size"), int) else None
                if self.download_verified(asset.get("browser_download_url", ""), target, expected, size):
                    if target is exe_path:
                        exe_downloaded = True
                    else:
                        uf2_downloaded = True
                else:
                    integrity_error = True

            if integrity_error and not (exe_downloaded or uf2_downloaded):
                self.status_signal.emit("Помилка перевірки цілісності")
                return

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

    def fetch_checksums(self, assets):
        """Необов'язковий файл контрольних сум у релізі (якщо GitHub не надав digest)."""
        result = {}
        for asset in assets:
            name = (asset.get("name") or "").lower()
            if name in _CHECKSUM_FILE_NAMES or name.endswith(".sha256"):
                try:
                    r = requests.get(asset.get("browser_download_url", ""), headers=HEADERS, timeout=10)
                    if r.status_code == 200 and len(r.content) < 65536:
                        text = r.content.decode("utf-8", errors="ignore")
                        parsed = parse_checksums(text)
                        if not parsed and name.endswith(".sha256"):
                            # '<ім'я>.sha256' може містити лише сам хеш
                            m = re.match(r"^\s*([0-9a-fA-F]{64})\b", text)
                            if m:
                                parsed = {name[:-len(".sha256")]: m.group(1).lower()}
                        result.update(parsed)
                except Exception:
                    pass
        return result

    def download_verified(self, url, dest, expected_sha, expected_size=None):
        """Завантажує у .part, перевіряє розмір і SHA-256 і лише тоді перейменовує у dest."""
        part = dest + ".part"
        try:
            if not self.download_file(url, part):
                return False
            if not verify_file(part, expected_sha, expected_size):
                return False
            os.replace(part, dest)
            register_verified(dest, expected_sha)
            return True
        except Exception:
            return False
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass

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