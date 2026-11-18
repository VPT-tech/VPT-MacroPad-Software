"""Місток для наскрізного тесту розширення: справжній WebSocket-сервер програми
(threads.WebSocketServerThread), яким керують через stdin/stdout.

  stdin : рядки-команди, що йдуть розширенню як є (YT_PLAYPAUSE, YT_FWD:10 ...)
  stdout: READY <port> | CLIENTS <n> <версії> | FEEDBACK <json> | REJECTED <origin>
"""
import json
import os
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import conftest  # noqa: F401,E402  (стаби Windows-модулів)

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

import threads as th  # noqa: E402


def out(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    app = QCoreApplication([])
    srv = th.WebSocketServerThread(host="localhost", port=port)
    srv.yt_feedback.connect(lambda fb: out("FEEDBACK " + json.dumps(fb, ensure_ascii=False)))
    srv.start()

    state = {"clients": None, "rejected": 0}

    def poll():
        versions = sorted(v for v in srv.client_versions.values())
        snap = (len(srv.clients), tuple(versions))
        if snap != state["clients"] and srv.server is not None:
            if state["clients"] is None:
                out(f"READY {port}")
            state["clients"] = snap
            out(f"CLIENTS {snap[0]} {','.join(v or '-' for v in versions)}")
        while state["rejected"] < len(srv.rejected_origins):
            out(f"REJECTED {srv.rejected_origins[state['rejected']]}")
            state["rejected"] += 1

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(50)

    def reader():
        for line in sys.stdin:
            cmd = line.strip()
            if cmd == "QUIT":
                break
            if cmd:
                ok = srv.send_command(cmd)
                if not ok:
                    out("NOCLIENT " + cmd)
        srv.stop()
        time.sleep(0.3)
        QTimer.singleShot(0, app.quit)

    threading.Thread(target=reader, daemon=True).start()
    app.exec()
    srv.wait(2000)


if __name__ == "__main__":
    main()
