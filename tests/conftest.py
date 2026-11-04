# Спільні фікстури тестів Python-клієнта.
# Windows-специфічні модулі (comtypes, pycaw, pyautogui, keyboard, mouse) підміняються
# стабами, тож логіку можна перевіряти на будь-якій ОС:  QT_QPA_PLATFORM=offscreen pytest tests
import os
import sys
import types

import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Конфіг програми пишеться в %APPDATA% — у тестах це тимчасова тека, а не домашній каталог
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="vpt_test_appdata_")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _install_stubs():
    if "comtypes" not in sys.modules:
        comtypes = types.ModuleType("comtypes")
        comtypes.CoInitialize = lambda *a, **k: None
        comtypes.CoUninitialize = lambda *a, **k: None
        comtypes.CLSCTX_ALL = 23
        sys.modules["comtypes"] = comtypes

    if "pycaw" not in sys.modules:
        pycaw = types.ModuleType("pycaw")
        pycaw_pycaw = types.ModuleType("pycaw.pycaw")

        class AudioUtilities:
            @staticmethod
            def GetAllSessions():
                return []

            @staticmethod
            def GetDeviceEnumerator():
                raise OSError("no audio in tests")

        class _Enum:
            def __init__(self, v):
                self.value = v

        class EDataFlow:
            eRender = _Enum(0)
            eCapture = _Enum(1)

        class ERole:
            eMultimedia = _Enum(1)

        class IAudioEndpointVolume:
            _iid_ = None

        pycaw_pycaw.AudioUtilities = AudioUtilities
        pycaw_pycaw.EDataFlow = EDataFlow
        pycaw_pycaw.ERole = ERole
        pycaw_pycaw.IAudioEndpointVolume = IAudioEndpointVolume
        pycaw.pycaw = pycaw_pycaw
        sys.modules["pycaw"] = pycaw
        sys.modules["pycaw.pycaw"] = pycaw_pycaw

    for name in ("pyautogui", "keyboard", "mouse"):
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.PAUSE = 0
            m.calls = []
            for fn in ("press", "keyDown", "keyUp", "scroll", "on_press", "unhook", "hook", "unhook_all"):
                setattr(m, fn, (lambda _fn: (lambda *a, **k: m.calls.append((_fn, a))))(fn))
            m.KEY_DOWN, m.KEY_UP = "down", "up"
            sys.modules[name] = m


_install_stubs()

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def process_events_for(qapp, ms):
    """Крутить цикл подій Qt заданий час (для QTimer-ів машини станів)."""
    import time
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.002)
    qapp.processEvents()
