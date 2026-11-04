# config.py
import os

APPDATA_DIR = os.getenv('APPDATA', os.path.expanduser("~"))
CONFIG_FILE = os.path.join(APPDATA_DIR, "macropad_config.json")
APP_PATH_CACHE = {}

BG_MAIN = "#0a0a0a"
BG_PANEL = "#111111"
BG_HOVER = "#1f1f1f"
ACCENT = "#00e5ff"
TEXT_MAIN = "#ffffff"
TEXT_SUB = "#888888"
BTN_DANGER = "#ff3366"

FRIENDLY_NAMES = {
    "NONE": "НЕ ПРИЗНАЧЕНО",
    "ENC:VOL": "Загальна гучність",
    "ENC:SCROLL": "Прокрутка сторінки",
    "ENC:BRIGHTNESS": "Яскравість монітора",
    "ENC:ZOOM": "Масштаб (Ctrl+ / Ctrl-)",
    "ENC:TIMELINE": "Таймлайн (⬅ / ➡)",
    "ENC:BRUSH": "Розмір пензля ([ / ])",
    "ENC:UNDO_REDO": "Історія (Undo / Redo)",
    "ENC:MODE_TOGGLE": "Зміна режиму крутилки (Smart Dial)",
    "SYS:SLEEP": "Режим сну",
    "SYS:SNIP": "Скріншот",
    "SYS:TASK": "Диспетчер завдань",
    "SYS:DESKTOP": "Згорнути вікна",
    "SYS:LOCK": "Блокування ПК",
    "SYS:PROFILE_NEXT": "Наступний профіль",
    "SYS:PROFILE_PREV": "Попередній профіль",
    "MED:PLAY": "Play / Pause",
    "MED:NEXT": "Наступний трек",
    "MED:PREV": "Попередній трек",
    "MED:MUTE": "Вимкнути звук (Система)",
    "MED:MIC_MUTE": "Вимкнути мікрофон",
    "MED:VOL_UP": "Збільшити гучність",
    "MED:VOL_DOWN": "Зменшити гучність",
    "HOTKEY:ctrl+c": "Копіювати",
    "HOTKEY:ctrl+v": "Вставити",
    "HOTKEY:ctrl+x": "Вирізати",
    "HOTKEY:ctrl+z": "Скасувати",
    "HOTKEY:ctrl+a": "Виділити все",
    "HOTKEY:ctrl+s": "Зберегти",
    "HOTKEY:alt+f4": "Закрити вікно",
    "CMD:start spotify:": "Spotify",
    "EXT:YT_FWD": "Ютуб: Вперед",
    "EXT:YT_BACK": "Ютуб: Назад",
    "EXT:YT_PLAYPAUSE": "Ютуб: Play / Pause"
}

VK_MAP = {
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45, 'f': 0x46, 'g': 0x47, 'h': 0x48,
    'i': 0x49, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F, 'p': 0x50,
    'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54, 'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58,
    'y': 0x59, 'z': 0x5A, '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35,
    '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B, 'windows': 0x5B,
    'left ctrl': 0xA2, 'right ctrl': 0xA3, 'left alt': 0xA4, 'right alt': 0xA5,
    'left shift': 0xA0, 'right shift': 0xA1, 'left windows': 0x5B, 'right windows': 0x5C,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75,
    'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'f13': 0x7C, 'f14': 0x7D, 'f15': 0x7E, 'f16': 0x7F, 'f17': 0x80, 'f18': 0x81,
    'f19': 0x82, 'f20': 0x83, 'f21': 0x84, 'f22': 0x85, 'f23': 0x86, 'f24': 0x87,
    'esc': 0x1B, 'tab': 0x09, 'space': 0x20, 'enter': 0x0D, 'num enter': 0x0D, 'backspace': 0x08,
    'delete': 0x2E, 'insert': 0x2D, 'home': 0x24, 'end': 0x23, 'page up': 0x21, 'page down': 0x22,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
    'print screen': 0x2C, 'caps lock': 0x14, 'num lock': 0x90, 'scroll lock': 0x91,
    'menu': 0x5D, 'playpause': 0xB3, 'nexttrack': 0xB0, 'prevtrack': 0xB1,
    'volumemute': 0xAD, 'volumeup': 0xAF, 'volumedown': 0xAE, '*': 0x6A, '+': 0x6B,
    'num 0': 0x60, 'num 1': 0x61, 'num 2': 0x62, 'num 3': 0x63,
    'num 4': 0x64, 'num 5': 0x65, 'num 6': 0x66, 'num 7': 0x67,
    'num 8': 0x68, 'num 9': 0x69, 'num /': 0x6F, 'num *': 0x6A,
    'num -': 0x6D, 'num +': 0x6B, 'num .': 0x6E,
    'й': 0x51, 'ц': 0x57, 'у': 0x45, 'к': 0x52, 'е': 0x54, 'н': 0x59, 'г': 0x55, 'ш': 0x49, 'щ': 0x4F, 'з': 0x50,
    'х': 0xDB, 'ї': 0xDD, 'ъ': 0xDD, 'ф': 0x41, 'і': 0x53, 'ы': 0x53, 'в': 0x44, 'а': 0x46, 'п': 0x47, 'р': 0x48,
    'о': 0x4A, 'л': 0x4B, 'д': 0x4C, 'ж': 0xBA, 'є': 0xDE, 'э': 0xDE, 'я': 0x5A, 'ч': 0x58, 'с': 0x43, 'м': 0x56,
    'и': 0x42, 'т': 0x4E, 'ь': 0x4D, 'б': 0xBC, 'ю': 0xBE, 'ґ': 0xDC
}

# Повна таблиця кодів клавіш Arduino Keyboard.h (включно з Numpad та F13-F24)
ARDUINO_HID_KEY_MAP = {
    'esc': 0xB1, 'tab': 0xB3, 'caps lock': 0xC1, 'enter': 0xB0, 'backspace': 0xB2,
    'insert': 0xD1, 'delete': 0xD4, 'home': 0xD2, 'end': 0xD5, 'page up': 0xD3, 'page down': 0xD6,
    'up': 0xDA, 'down': 0xD9, 'left': 0xD8, 'right': 0xD7, 'print screen': 0xCE, 'space': 0x20,
    'menu': 0xED, 'scroll lock': 0xCF,
    'f1': 0xC2, 'f2': 0xC3, 'f3': 0xC4, 'f4': 0xC5, 'f5': 0xC6, 'f6': 0xC7,
    'f7': 0xC8, 'f8': 0xC9, 'f9': 0xCA, 'f10': 0xCB, 'f11': 0xCC, 'f12': 0xCD,
    'f13': 0xF0, 'f14': 0xF1, 'f15': 0xF2, 'f16': 0xF3, 'f17': 0xF4, 'f18': 0xF5,
    'f19': 0xF6, 'f20': 0xF7, 'f21': 0xF8, 'f22': 0xF9, 'f23': 0xFA, 'f24': 0xFB,
    'num lock': 0xDB, 'num /': 0xDC, 'num *': 0xDD, 'num -': 0xDE, 'num +': 0xDF,
    'num enter': 0xE0, 'num 1': 0xE1, 'num 2': 0xE2, 'num 3': 0xE3, 'num 4': 0xE4,
    'num 5': 0xE5, 'num 6': 0xE6, 'num 7': 0xE7, 'num 8': 0xE8, 'num 9': 0xE9,
    'num 0': 0xEA, 'num .': 0xEB
}

MEDIA_HID_MAP = {
    "MED:PLAY": "HID_MEDIA:1",
    "MED:NEXT": "HID_MEDIA:2",
    "MED:PREV": "HID_MEDIA:3",
    "MED:MUTE": "HID_MEDIA:4",
    "MED:VOL_UP": "HID_MEDIA:5",
    "MED:VOL_DOWN": "HID_MEDIA:6",
}

SYS_TO_HOTKEY_MAP = {
    "SYS:TASK": "HOTKEY:ctrl+shift+esc",
    "SYS:DESKTOP": "HOTKEY:win+d",
    "SYS:SNIP": "HOTKEY:win+shift+s",
    "SYS:LOCK": "HOTKEY:win+l",
}

def split_hotkey_tokens(combo: str) -> list[str]:
    """Безпечно розбиває рядок гарячих клавіш, зберігаючи 'num +' та '+'."""
    s = combo.lower().strip()
    if not s:
        return []
    # Плейсхолдери мають бути в нижньому регістрі: рядок уже переведено в lower(),
    # і порівняння нижче теж іде в нижньому регістрі (раніше "num +" і "ctrl++" не працювали).
    placeholder_num_plus = "\x00num_plus\x00"
    placeholder_plus = "\x00plus_key\x00"
    s = s.replace("num +", placeholder_num_plus)
    while "++" in s:
        s = s.replace("++", "+" + placeholder_plus, 1)
    if s == "+":
        s = placeholder_plus
    tokens = []
    for p in s.split("+"):
        p = p.strip()
        if not p:
            continue
        if p == placeholder_num_plus:
            tokens.append("num +")
        elif p == placeholder_plus:
            tokens.append("+")
        else:
            tokens.append(p)
    return tokens

def action_to_hid_spec(act: str) -> str:
    """Конвертує дію кнопки у специфікацію для автономної прошивки RP2040 або SERIAL."""
    if not act or act == "NONE":
        return "NONE"
    if act in MEDIA_HID_MAP:
        return MEDIA_HID_MAP[act]
    if act in SYS_TO_HOTKEY_MAP:
        act = SYS_TO_HOTKEY_MAP[act]

    if act.startswith("HOTKEY:"):
        combo = act.split(":", 1)[1].lower().strip()
        if combo == "mouse_left": return "HID_MOUSE:1"
        if combo == "mouse_right": return "HID_MOUSE:2"
        if combo == "mouse_middle": return "HID_MOUSE:3"
        if combo in ("mouse_wheel_up", "mouse_scroll_up"): return "HID_MOUSE:4"
        if combo in ("mouse_wheel_down", "mouse_scroll_down"): return "HID_MOUSE:5"

        parts = split_hotkey_tokens(combo)
        mod_mask = 0
        main_key = 0
        for p in parts:
            if p in ("ctrl", "left ctrl", "right ctrl"): mod_mask |= 1
            elif p in ("shift", "left shift", "right shift"): mod_mask |= 2
            elif p in ("alt", "left alt", "right alt"): mod_mask |= 4
            elif p in ("win", "windows", "left windows", "right windows"): mod_mask |= 8
            elif p in ARDUINO_HID_KEY_MAP:
                if main_key != 0: return "SERIAL"
                main_key = ARDUINO_HID_KEY_MAP[p]
            elif len(p) == 1 and 32 <= ord(p) <= 126:
                if main_key != 0: return "SERIAL"
                main_key = ord(p)
            else:
                return "SERIAL"
        if mod_mask != 0 or main_key != 0:
            return f"HID_KEY:{mod_mask}:{main_key}"
    return "SERIAL"

def encoder_action_to_hid_spec(act: str, is_right: bool) -> str:
    """Конвертує дію обертання енкодера у специфікацію автономного HID для RP2040."""
    if not act or act == "NONE":
        return "NONE"
    if act == "ENC:VOL":
        return "HID_MEDIA:5" if is_right else "HID_MEDIA:6"
    if act == "ENC:SCROLL":
        return "HID_MOUSE:5" if is_right else "HID_MOUSE:4"
    if act == "ENC:ZOOM":
        return action_to_hid_spec("HOTKEY:ctrl+=" if is_right else "HOTKEY:ctrl+-")
    if act == "ENC:TIMELINE":
        return action_to_hid_spec("HOTKEY:right" if is_right else "HOTKEY:left")
    if act == "ENC:BRUSH":
        return action_to_hid_spec("HOTKEY:]" if is_right else "HOTKEY:[")
    if act == "ENC:UNDO_REDO":
        return action_to_hid_spec("HOTKEY:ctrl+y" if is_right else "HOTKEY:ctrl+z")
    return action_to_hid_spec(act)

BUILTIN_PRESETS = {
    "Мультимедіа": {
        "name": "Мультимедіа",
        "app_bind": "",
        "actions": {
            "BTN_1": {"tap": "MED:PREV", "dtap": "NONE", "hold": "NONE"},
            "BTN_2": {"tap": "MED:PLAY", "dtap": "MED:NEXT", "hold": "MED:MUTE"},
            "BTN_3": {"tap": "MED:NEXT", "dtap": "NONE", "hold": "NONE"},
            "BTN_4": {"tap": "HOTKEY:ctrl+c", "dtap": "HOTKEY:ctrl+x", "hold": "NONE"},
            "BTN_5": {"tap": "HOTKEY:ctrl+v", "dtap": "HOTKEY:ctrl+z", "hold": "NONE"},
            "BTN_6": {"tap": "SYS:SNIP", "dtap": "NONE", "hold": "SYS:TASK"},
            "BTN_7": {"tap": "MED:MIC_MUTE", "dtap": "NONE", "hold": "NONE"},
            "BTN_8": {"tap": "SYS:DESKTOP", "dtap": "NONE", "hold": "SYS:LOCK"},
            "BTN_9": {"tap": "SYS:PROFILE_NEXT", "dtap": "SYS:PROFILE_PREV", "hold": "NONE"},
            "ENC_1": "ENC:VOL",
            "ENC_1_SW": {"tap": "ENC:MODE_TOGGLE", "dtap": "MED:MUTE", "hold": "NONE"},
            "ENC_2": "ENC:SCROLL",
            "ENC_2_SW": {"tap": "MED:MIC_MUTE", "dtap": "NONE", "hold": "NONE"},
            "ENC_3": "ENC:BRIGHTNESS",
            "ENC_3_SW": {"tap": "EXT:YT_PLAYPAUSE", "dtap": "NONE", "hold": "NONE"}
        },
        "enc_modes": {
            "ENC_1": ["ENC:VOL", "ENC:APP:discord.exe", "ENC:APP:spotify.exe"]
        }
    },
    "Blender 3D": {
        "name": "Blender 3D",
        "app_bind": "blender.exe",
        "actions": {
            "BTN_1": {"tap": "HOTKEY:num 1", "dtap": "HOTKEY:ctrl+num 1", "hold": "NONE"},
            "BTN_2": {"tap": "HOTKEY:num 3", "dtap": "HOTKEY:ctrl+num 3", "hold": "NONE"},
            "BTN_3": {"tap": "HOTKEY:num 7", "dtap": "HOTKEY:ctrl+num 7", "hold": "NONE"},
            "BTN_4": {"tap": "HOTKEY:g", "dtap": "HOTKEY:r", "hold": "HOTKEY:s"},
            "BTN_5": {"tap": "HOTKEY:tab", "dtap": "HOTKEY:z", "hold": "NONE"},
            "BTN_6": {"tap": "HOTKEY:e", "dtap": "HOTKEY:i", "hold": "HOTKEY:ctrl+b"},
            "BTN_7": {"tap": "HOTKEY:shift+a", "dtap": "HOTKEY:x", "hold": "NONE"},
            "BTN_8": {"tap": "HOTKEY:ctrl+z", "dtap": "HOTKEY:ctrl+shift+z", "hold": "HOTKEY:ctrl+s"},
            "BTN_9": {"tap": "SYS:PROFILE_NEXT", "dtap": "NONE", "hold": "NONE"},
            "ENC_1": "ENC:ZOOM",
            "ENC_1_SW": {"tap": "HOTKEY:num .", "dtap": "NONE", "hold": "NONE"},
            "ENC_2": "ENC:BRUSH",
            "ENC_2_SW": {"tap": "HOTKEY:num 0", "dtap": "NONE", "hold": "NONE"},
            "ENC_3": "ENC:TIMELINE",
            "ENC_3_SW": {"tap": "HOTKEY:space", "dtap": "NONE", "hold": "NONE"}
        }
    },
    "Photoshop": {
        "name": "Photoshop",
        "app_bind": "photoshop.exe",
        "actions": {
            "BTN_1": {"tap": "HOTKEY:b", "dtap": "HOTKEY:e", "hold": "NONE"},
            "BTN_2": {"tap": "HOTKEY:v", "dtap": "HOTKEY:m", "hold": "NONE"},
            "BTN_3": {"tap": "HOTKEY:l", "dtap": "HOTKEY:w", "hold": "NONE"},
            "BTN_4": {"tap": "HOTKEY:ctrl+t", "dtap": "HOTKEY:ctrl+d", "hold": "NONE"},
            "BTN_5": {"tap": "HOTKEY:ctrl+shift+n", "dtap": "HOTKEY:ctrl+j", "hold": "NONE"},
            "BTN_6": {"tap": "HOTKEY:x", "dtap": "HOTKEY:d", "hold": "NONE"},
            "BTN_7": {"tap": "HOTKEY:ctrl+z", "dtap": "HOTKEY:ctrl+shift+z", "hold": "NONE"},
            "BTN_8": {"tap": "HOTKEY:space", "dtap": "HOTKEY:ctrl+0", "hold": "HOTKEY:ctrl+s"},
            "BTN_9": {"tap": "SYS:PROFILE_NEXT", "dtap": "NONE", "hold": "NONE"},
            "ENC_1": "ENC:BRUSH",
            "ENC_1_SW": {"tap": "ENC:MODE_TOGGLE", "dtap": "NONE", "hold": "NONE"},
            "ENC_2": "ENC:ZOOM",
            "ENC_2_SW": {"tap": "HOTKEY:ctrl+0", "dtap": "NONE", "hold": "NONE"},
            "ENC_3": "ENC:UNDO_REDO",
            "ENC_3_SW": {"tap": "MED:PLAY", "dtap": "NONE", "hold": "NONE"}
        },
        "enc_modes": {
            "ENC_1": ["ENC:BRUSH", "ENC:ZOOM"]
        }
    },
    "Premiere Pro": {
        "name": "Premiere Pro",
        "app_bind": "adobe premiere pro.exe",
        "actions": {
            "BTN_1": {"tap": "HOTKEY:v", "dtap": "HOTKEY:a", "hold": "NONE"},
            "BTN_2": {"tap": "HOTKEY:c", "dtap": "HOTKEY:ctrl+k", "hold": "NONE"},
            "BTN_3": {"tap": "HOTKEY:delete", "dtap": "HOTKEY:shift+delete", "hold": "NONE"},
            "BTN_4": {"tap": "HOTKEY:i", "dtap": "HOTKEY:o", "hold": "NONE"},
            "BTN_5": {"tap": "HOTKEY:space", "dtap": "HOTKEY:l", "hold": "NONE"},
            "BTN_6": {"tap": "HOTKEY:m", "dtap": "NONE", "hold": "NONE"},
            "BTN_7": {"tap": "HOTKEY:ctrl+z", "dtap": "HOTKEY:ctrl+shift+z", "hold": "NONE"},
            "BTN_8": {"tap": "HOTKEY:ctrl+s", "dtap": "HOTKEY:ctrl+m", "hold": "NONE"},
            "BTN_9": {"tap": "SYS:PROFILE_NEXT", "dtap": "NONE", "hold": "NONE"},
            "ENC_1": "ENC:TIMELINE",
            "ENC_1_SW": {"tap": "HOTKEY:space", "dtap": "NONE", "hold": "NONE"},
            "ENC_2": "ENC:ZOOM",
            "ENC_2_SW": {"tap": "HOTKEY:\\", "dtap": "NONE", "hold": "NONE"},
            "ENC_3": "ENC:VOL",
            "ENC_3_SW": {"tap": "MED:MUTE", "dtap": "NONE", "hold": "NONE"}
        }
    },
    "VS Code": {
        "name": "VS Code",
        "app_bind": "code.exe",
        "actions": {
            "BTN_1": {"tap": "HOTKEY:ctrl+p", "dtap": "HOTKEY:ctrl+shift+p", "hold": "NONE"},
            "BTN_2": {"tap": "HOTKEY:ctrl+/", "dtap": "HOTKEY:shift+alt+f", "hold": "NONE"},
            "BTN_3": {"tap": "HOTKEY:ctrl+`", "dtap": "HOTKEY:ctrl+b", "hold": "NONE"},
            "BTN_4": {"tap": "HOTKEY:ctrl+f", "dtap": "HOTKEY:ctrl+h", "hold": "NONE"},
            "BTN_5": {"tap": "HOTKEY:f5", "dtap": "HOTKEY:ctrl+f5", "hold": "NONE"},
            "BTN_6": {"tap": "HOTKEY:alt+up", "dtap": "HOTKEY:alt+down", "hold": "NONE"},
            "BTN_7": {"tap": "HOTKEY:ctrl+c", "dtap": "HOTKEY:ctrl+v", "hold": "NONE"},
            "BTN_8": {"tap": "HOTKEY:ctrl+z", "dtap": "HOTKEY:ctrl+s", "hold": "NONE"},
            "BTN_9": {"tap": "SYS:PROFILE_NEXT", "dtap": "NONE", "hold": "NONE"},
            "ENC_1": "ENC:SCROLL",
            "ENC_1_SW": {"tap": "ENC:MODE_TOGGLE", "dtap": "NONE", "hold": "NONE"},
            "ENC_2": "ENC:ZOOM",
            "ENC_2_SW": {"tap": "MED:PLAY", "dtap": "NONE", "hold": "NONE"},
            "ENC_3": "ENC:VOL",
            "ENC_3_SW": {"tap": "MED:MIC_MUTE", "dtap": "NONE", "hold": "NONE"}
        }
    },
    "CS2 (Gaming)": {
        "name": "CS2 (Gaming)",
        "app_bind": "cs2.exe",
        "actions": {
            "BTN_1": {"tap": "HOTKEY:f13", "dtap": "NONE", "hold": "NONE"},
            "BTN_2": {"tap": "HOTKEY:f14", "dtap": "NONE", "hold": "NONE"},
            "BTN_3": {"tap": "HOTKEY:f15", "dtap": "NONE", "hold": "NONE"},
            "BTN_4": {"tap": "HOTKEY:f16", "dtap": "NONE", "hold": "NONE"},
            "BTN_5": {"tap": "HOTKEY:f17", "dtap": "NONE", "hold": "NONE"},
            "BTN_6": {"tap": "HOTKEY:f18", "dtap": "NONE", "hold": "NONE"},
            "BTN_7": {"tap": "MED:MIC_MUTE", "dtap": "NONE", "hold": "NONE"},
            "BTN_8": {"tap": "MED:PLAY", "dtap": "MED:NEXT", "hold": "NONE"},
            "BTN_9": {"tap": "SYS:PROFILE_NEXT", "dtap": "NONE", "hold": "NONE"},
            "ENC_1": "ENC:VOL",
            "ENC_1_SW": {"tap": "ENC:MODE_TOGGLE", "dtap": "MED:MUTE", "hold": "NONE"},
            "ENC_2": "ENC:APP:discord.exe",
            "ENC_2_SW": {"tap": "APP_MUTE:discord.exe", "dtap": "NONE", "hold": "NONE"},
            "ENC_3": "ENC:BRIGHTNESS",
            "ENC_3_SW": {"tap": "SYS:SNIP", "dtap": "NONE", "hold": "NONE"}
        },
        "enc_modes": {
            "ENC_1": ["ENC:VOL", "ENC:APP:discord.exe"]
        }
    }
}

STYLESHEET = f"""
QMainWindow, QDialog, QInputDialog {{ background-color: {BG_MAIN}; color: {TEXT_MAIN}; }}
QFrame#leftPanel {{ background-color: {BG_PANEL}; border-right: 1px solid #222; }}
QLabel {{ color: {TEXT_MAIN}; }}
QPushButton {{ background-color: transparent; border: 1px solid #333; color: {TEXT_MAIN}; border-radius: 5px; padding: 10px; font-weight: bold; }}
QPushButton:hover {{ background-color: {BG_HOVER}; border: 1px solid {ACCENT}; }}
QPushButton:disabled {{ color: #444; border: 1px solid #222; }}
QPushButton#tabBtn {{ border: none; padding: 8px; border-radius: 5px; color: {TEXT_SUB}; }}
QPushButton#tabBtn:hover {{ background-color: {BG_HOVER}; }}
QPushButton#tabBtn[active="true"] {{ background-color: {ACCENT}; color: {BG_MAIN}; }}
QPushButton#padBtn {{ background-color: {BG_PANEL}; border-radius: 15px; font-size: 20px; }}
QPushButton#padBtn[active="true"] {{ border: 2px solid {ACCENT}; }}
QPushButton#encBtn {{ background-color: {BG_PANEL}; border-radius: 40px; font-size: 16px; }}
QPushButton#encBtn[active="true"] {{ border: 2px solid {ACCENT}; }}
QPushButton#swBtn {{ background-color: {BG_PANEL}; border-radius: 5px; font-size: 11px; padding: 0px; }}
QPushButton#swBtn[active="true"] {{ border: 2px solid {ACCENT}; }}
QPushButton#assignBtn {{ background-color: {BG_HOVER}; border: none; font-size: 14px; }}
QPushButton#assignBtn[ready="true"] {{ background-color: {ACCENT}; color: {BG_MAIN}; }}
QPushButton#delBtn {{ background-color: transparent; border: 1px solid {BTN_DANGER}; color: {BTN_DANGER}; border-radius: 5px; font-size: 16px; padding: 5px; }}
QPushButton#delBtn:hover {{ background-color: {BTN_DANGER}; color: white; }}
QPushButton#actionBtn {{ background-color: transparent; border: 1px solid #333; text-align: left; padding-left: 15px; }}
QPushButton#actionBtn:hover {{ background-color: {BG_HOVER}; border: 1px solid {ACCENT}; }}
QPushButton#actionBtn[staged="true"] {{ background-color: #1a2a3a; border: 1px solid {ACCENT}; color: {ACCENT}; }}

QComboBox {{ background-color: #1a1a1a; border: 1px solid #444; color: #ffffff; border-radius: 5px; padding: 8px; font-size: 14px; }}
QComboBox:hover {{ border: 1px solid #666; }}
QComboBox::drop-down {{ border: none; width: 30px; }}
QComboBox QAbstractItemView {{ background-color: #222222; color: #ffffff; selection-background-color: #444444; selection-color: #ffffff; outline: none; border: 1px solid #444; border-radius: 5px; }}

QLineEdit {{ background-color: {BG_MAIN}; border: 1px solid #333; color: {TEXT_MAIN}; border-radius: 5px; padding: 8px; font-size: 14px; }}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QScrollArea {{ border: none; background-color: transparent; }}
QScrollArea > QWidget > QWidget {{ background-color: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: #333; border-radius: 4px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background: #555; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: #333; border-radius: 4px; min-width: 20px; }}
QScrollBar::handle:horizontal:hover {{ background: #555; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QMenu {{ background-color: #151515; color: #fff; border: 1px solid #333; border-radius: 8px; font-size: 13px; padding: 5px; }}
QMenu::item {{ padding: 8px 25px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: #333333; color: #ffffff; }}
QMenu::item:selected#danger {{ background-color: {BTN_DANGER}; color: white; }}

QFrame#profileFrame {{ background-color: {BG_PANEL}; border: 1px solid #333; border-radius: 8px; }}
QFrame#profileFrame[active="true"] {{ background-color: transparent; border: 2px solid {ACCENT}; }}
QFrame#profileFrame:hover {{ border: 1px solid {ACCENT}; background-color: {BG_HOVER}; }}
QFrame#profileFrame[active="true"]:hover {{ background-color: rgba(0, 229, 255, 0.05); }}
QLabel#profileNum {{ font-size: 16px; font-weight: bold; color: {TEXT_MAIN}; background: transparent; border: none; }}
QLabel#profileNum[active="true"] {{ color: {ACCENT}; }}
QLabel#profileName {{ font-size: 14px; font-weight: bold; color: {TEXT_MAIN}; background: transparent; border: none; padding-right: 10px; }}
QLabel#profileName[active="true"] {{ color: {ACCENT}; }}
QPushButton#addProfileBtn {{
    background-color: transparent;
    border: 1px dashed #444;
    border-radius: 8px;
    color: #888;
    font-size: 26px;
    font-family: Arial;
    padding: 0px 0px 3px 1px;
    font-weight: normal;
}}
QPushButton#addProfileBtn:hover {{
    border: 1px solid {ACCENT};
    color: {ACCENT};
    background-color: rgba(0, 229, 255, 0.1);
}}
"""