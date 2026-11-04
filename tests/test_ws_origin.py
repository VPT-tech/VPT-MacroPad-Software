"""WebSocket-сервер для розширення YouTube приймає лише розширення браузера та сторінки YouTube."""
import asyncio
import socket
import time

import pytest
import websockets

import threads as th


@pytest.mark.parametrize("origin,ok", [
    (None, True),                                   # не браузер (локальна програма)
    ("chrome-extension://deihndpelcbeahgbambapfmaaidhonni", True),
    ("moz-extension://1234-abcd", True),
    ("https://www.youtube.com", True),
    ("https://music.youtube.com/", True),
    ("https://evil.example", False),
    ("https://youtube.com.evil.example", False),
    ("http://localhost:3000", False),
    ("null", False),                                # file://, sandbox iframe
    ("", False),
])
def test_origin_policy(origin, ok):
    assert th.is_allowed_ws_origin(origin) is ok


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _client(port, origin, wait_cmd):
    kwargs = {"origin": origin} if origin else {}
    async with websockets.connect(f"ws://127.0.0.1:{port}", **kwargs) as ws:
        try:
            return await asyncio.wait_for(ws.recv(), timeout=wait_cmd)
        except websockets.exceptions.ConnectionClosed as e:
            return ("closed", getattr(getattr(e, "rcvd", None), "code", None))
        except asyncio.TimeoutError:
            return None


def test_server_rejects_foreign_site_and_serves_extension(qapp):
    port = _free_port()
    srv = th.WebSocketServerThread(host="127.0.0.1", port=port)
    srv.start()
    try:
        end = time.monotonic() + 5
        while srv.server is None and time.monotonic() < end:
            time.sleep(0.02)
        assert srv.server is not None

        res = asyncio.run(_client(port, "https://evil.example", 2.0))
        assert res == ("closed", 1008)
        assert "https://evil.example" in srv.rejected_origins

        async def ext_flow():
            task = asyncio.create_task(_client(port, "chrome-extension://deihndpelcbeahgbambapfmaaidhonni", 3.0))
            end2 = time.monotonic() + 3
            while not srv.clients and time.monotonic() < end2:
                await asyncio.sleep(0.02)
            srv.send_command("YT_PLAYPAUSE")
            return await task

        assert asyncio.run(ext_flow()) == "YT_PLAYPAUSE"
    finally:
        srv.stop()
        srv.wait(2000)
