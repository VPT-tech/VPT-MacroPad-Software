"""Програмна частина керування YouTube: команди для дій, маршрутизація між кількома
браузерами, розбір відповідей розширення."""
import asyncio
import json
import socket
import time

import pytest
import websockets

import threads as th
from config import yt_command_for_action, yt_command_for_rotation, FRIENDLY_NAMES


@pytest.mark.parametrize("act,cmd", [
    ("EXT:YT_PLAYPAUSE", "YT_PLAYPAUSE"),
    ("EXT:YT_FWD:10", "YT_FWD:10"),
    ("EXT:YT_BACK:5", "YT_BACK:5"),
    ("EXT:YT_FWD", "YT_FWD:10"),          # старий формат без секунд
    ("EXT:YT_FWD:abc", "YT_FWD:10"),
    ("EXT:YT_BACK:99999", "YT_BACK:600"),
    ("EXT:YT_NEXT", "YT_NEXT"),
    ("EXT:YT_VOL_DOWN", "YT_VOL:-5"),
    ("EXT:YT_SPEED_RESET", "YT_SPEED:=1"),
    ("EXT:YT_LIKE", "YT_LIKE"),
    ("EXT:NOPE", None),
    ("MED:PLAY", None),
])
def test_button_commands(act, cmd):
    assert yt_command_for_action(act) == cmd


def test_every_yt_action_has_a_name_and_command():
    for act in FRIENDLY_NAMES:
        if act.startswith("EXT:YT_"):
            assert yt_command_for_action(act), act
        if act.startswith("ENC:YT_"):
            assert yt_command_for_rotation(act, True), act


def test_rotation_commands_scale_with_acceleration():
    assert yt_command_for_rotation("ENC:YT_SEEK", True, 1) == "YT_FWD:5"
    assert yt_command_for_rotation("ENC:YT_SEEK", False, 3) == "YT_BACK:15"
    assert yt_command_for_rotation("ENC:YT_VOL", True, 5) == "YT_VOL:15"
    assert yt_command_for_rotation("ENC:YT_VOL", False, 1) == "YT_VOL:-5"
    assert yt_command_for_rotation("ENC:YT_SPEED", False, 5) == "YT_SPEED:-0.25"
    assert yt_command_for_rotation("ENC:VOL", True) is None


def test_feedback_is_sanitized():
    fb = th.sanitize_yt_feedback({
        "cmd": "SEEK", "ok": True, "title": "  a\n\tb  " + "x" * 500, "time": float("nan"),
        "dur": "100", "vol": 250, "rate": True, "paused": "yes", "evil": "<script>",
    })
    assert fb["ok"] is True and fb["cmd"] == "SEEK"
    assert fb["title"].startswith("a b") and len(fb["title"]) <= 120
    assert fb["time"] == 0.0 and fb["dur"] == 0.0 and fb["vol"] == 100.0 and fb["rate"] == 1.0
    assert fb["paused"] is False and "evil" not in fb
    assert th.sanitize_yt_feedback({"ok": 1})["ok"] is False


# ------------------------------------------------------------ маршрутизація між браузерами
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(qapp):
    port = _free_port()
    srv = th.WebSocketServerThread(host="127.0.0.1", port=port)
    feedback = []
    srv.yt_feedback.connect(feedback.append, type=__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ConnectionType.DirectConnection)
    srv.start()
    end = time.monotonic() + 5
    while srv.server is None and time.monotonic() < end:
        time.sleep(0.02)
    assert srv.server is not None
    srv.feedback = feedback
    yield srv, port
    srv.stop()
    srv.wait(2000)


class Browser:
    """Імітація розширення: hello/active, отримує команди, відповідає result."""

    def __init__(self, port, version="2.0.0", has_video=True):
        self.port, self.version, self.has_video = port, version, has_video
        self.got = []

    async def run(self, ready, stop):
        async with websockets.connect(f"ws://127.0.0.1:{self.port}", origin="chrome-extension://test") as ws:
            if self.version:
                await ws.send(json.dumps({"t": "hello", "v": self.version}))
            ready.set()
            while not stop.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), 0.1)
                except asyncio.TimeoutError:
                    continue
                if isinstance(msg, str) and msg.startswith("CTRL:"):
                    await ws.send(msg[5:])
                    continue
                self.got.append(msg)
                if self.version:
                    res = {"t": "result", "cmd": "PLAYPAUSE", "ok": self.has_video,
                           **({} if self.has_video else {"err": "no_video"}), "title": f"from {self.version}"}
                    await ws.send(json.dumps(res))


async def _scenario(srv, browsers, actions):
    stop = asyncio.Event()
    readies = [asyncio.Event() for _ in browsers]
    tasks = []
    for b, r in zip(browsers, readies):
        tasks.append(asyncio.create_task(b.run(r, stop)))
        await r.wait()
        await asyncio.sleep(0.15)    # фіксований порядок підключення
    for act in actions:
        await act()
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)


def test_command_goes_to_one_browser_only(server):
    srv, port = server
    a, b = Browser(port, "2.0.0"), Browser(port, "2.0.1")

    async def send():
        assert srv.send_command("YT_PLAYPAUSE") is True
        await asyncio.sleep(0.4)

    asyncio.run(_scenario(srv, [a, b], [send]))
    # жоден браузер не повідомив, що грає -> останній підключений
    assert (len(a.got), len(b.got)) == (0, 1)


def test_active_browser_is_preferred(server):
    srv, port = server
    a, b = Browser(port, "2.0.0"), Browser(port, "2.0.1")

    async def a_becomes_active():
        # браузер A повідомляє, що в ньому заграло відео
        for ws in list(srv.clients):
            if srv.client_versions.get(ws) == "2.0.0":
                srv._preferred = ws
        assert srv.send_command("YT_PLAYPAUSE")
        await asyncio.sleep(0.4)

    asyncio.run(_scenario(srv, [a, b], [a_becomes_active]))
    assert (len(a.got), len(b.got)) == (1, 0)


def test_retry_in_other_browser_when_no_video(server):
    srv, port = server
    a = Browser(port, "2.0.0", has_video=True)
    b = Browser(port, "2.0.1", has_video=False)    # останній підключений, але відео там немає

    async def send():
        srv.send_command("YT_PLAYPAUSE")
        await asyncio.sleep(0.6)

    asyncio.run(_scenario(srv, [a, b], [send]))
    assert (len(a.got), len(b.got)) == (1, 1)
    # програма отримала одну відповідь — успішну, з браузера A
    assert [f["ok"] for f in srv.feedback] == [True]
    assert srv.feedback[0]["title"] == "from 2.0.0"


def test_legacy_extension_still_gets_commands(server):
    srv, port = server
    old = Browser(port, version="")      # старе розширення: без hello і без відповідей

    async def send():
        assert srv.send_command("YT_FWD:10")
        await asyncio.sleep(0.3)

    asyncio.run(_scenario(srv, [old], [send]))
    assert old.got == ["YT_FWD:10"]


def test_no_clients_reports_false(server):
    srv, _ = server
    assert srv.send_command("YT_PLAYPAUSE") is False
