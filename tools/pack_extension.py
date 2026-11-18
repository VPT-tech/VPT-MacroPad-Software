"""Пакує розширення YouTube для Chrome Web Store: dist/VPT_Pad_YouTube_<версія>.zip.

Магазин вимагає, щоб manifest.json лежав у КОРЕНІ архіву (не в підтеці).
Запуск:  python tools/pack_extension.py
"""
import json
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXT = os.path.join(ROOT, "extension")
# Лише файли, потрібні браузеру (README та інструкції в архів не потрапляють)
RUNTIME_FILES = ["manifest.json", "background.js", "targeting.js", "page.js",
                 "popup.html", "popup.css", "popup.js"]


def main():
    with open(os.path.join(EXT, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    version = manifest["version"]
    files = list(RUNTIME_FILES)
    files += sorted(os.path.join("icons", n) for n in os.listdir(os.path.join(EXT, "icons")) if n.endswith(".png"))
    for rel in files:
        if not os.path.isfile(os.path.join(EXT, rel)):
            sys.exit(f"немає файлу: extension/{rel}")
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"VPT_Pad_YouTube_{version}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(os.path.join(EXT, rel), rel.replace(os.sep, "/"))
    print(f"{out}  ({len(files)} файлів, версія {version})")


if __name__ == "__main__":
    main()
