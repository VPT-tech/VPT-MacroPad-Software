# main.py
import sys
sys.coinit_flags = 2
import comtypes

import os
import traceback
import faulthandler
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from config import STYLESHEET, APPDATA_DIR
from main_window import MacroPadPro

_crash_log_handle = None
try:
    os.makedirs(APPDATA_DIR, exist_ok=True)
    crash_file_path = os.path.join(APPDATA_DIR, "FATAL_CRASH.txt")
    # Режим 'w' обнуляв файл при кожному запуску — трасування попереднього падіння
    # зникало ще до того, як його хтось побачить. Зберігаємо його як .prev.txt.
    if os.path.exists(crash_file_path) and os.path.getsize(crash_file_path) > 0:
        os.replace(crash_file_path, os.path.join(APPDATA_DIR, "FATAL_CRASH.prev.txt"))
    _crash_log_handle = open(crash_file_path, 'w', encoding='utf-8')
    faulthandler.enable(_crash_log_handle)
except Exception:
    pass

def global_exception_handler(exc_type, exc_value, exc_traceback):
    try:
        err_file = os.path.join(APPDATA_DIR, "crash_log.txt")
        with open(err_file, "w", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

if __name__ == "__main__":
    sys.excepthook = global_exception_handler
    app = QApplication(sys.argv)

    socket = QLocalSocket()
    socket.connectToServer("VPT_MacroPad_Server")

    if socket.waitForConnected(500):
        socket.write(b"WAKEUP")
        socket.waitForBytesWritten()
        socket.disconnectFromServer()
        sys.exit(0)

    server = QLocalServer()
    server.removeServer("VPT_MacroPad_Server")
    server.listen("VPT_MacroPad_Server")

    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLESHEET)

    window = MacroPadPro()

    def on_new_connection():
        client = server.nextPendingConnection()
        if client and client.waitForReadyRead(100):
            if client.readAll() == b"WAKEUP":
                window.show_window()
        if client:
            client.disconnectFromServer()

    server.newConnection.connect(on_new_connection)

    if "--tray" not in sys.argv:
        window.show()

    sys.exit(app.exec())