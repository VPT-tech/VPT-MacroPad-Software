"""Перевірка цілісності оновлень (SHA-256 + розмір) перед запуском з правами адміністратора."""
import hashlib
import os

import pytest

import updater


EXE = b"MZ fake installer payload" * 100
UF2 = b"UF2\n fake firmware" * 50


def _asset(name, data, digest="auto", size="auto"):
    a = {"name": name, "browser_download_url": f"https://example.invalid/{name}"}
    if digest == "auto":
        a["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
    elif digest is not None:
        a["digest"] = digest
    a["size"] = len(data) if size == "auto" else size
    return a


@pytest.fixture
def run_updater(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))

    def _run(release, served):
        monkeypatch.setattr(updater, "get_latest_release_data", lambda: release)
        th = updater.UpdaterThread()

        def fake_download(url, dest):
            name = url.rsplit("/", 1)[-1]
            if name not in served:
                return False
            with open(dest, "wb") as f:
                f.write(served[name])
            return True
        th.download_file = fake_download
        th.fetch_checksums = lambda assets: updater.parse_checksums(served.get("SHA256SUMS", b"").decode())
        statuses, ready = [], []
        th.status_signal.connect(statuses.append)
        th.update_ready_signal.connect(lambda e, u: ready.append((e, u)))
        th.run()   # синхронно, без потоку
        return statuses, ready
    return _run


def test_github_digest_verified(run_updater):
    rel = {"tag_name": "v9.9.9", "assets": [_asset("Setup.exe", EXE), _asset("firmware.uf2", UF2)]}
    statuses, ready = run_updater(rel, {"Setup.exe": EXE, "firmware.uf2": UF2})
    assert ready, statuses
    exe, uf2 = ready[0]
    assert updater.is_verified(exe) and updater.is_verified(uf2)
    assert not os.path.exists(exe + ".part")
    # Підміна файлу після завантаження (до підтвердження UAC) виявляється
    with open(exe, "ab") as f:
        f.write(b"evil")
    assert not updater.is_verified(exe)


def test_corrupted_download_rejected(run_updater):
    rel = {"tag_name": "v9.9.9", "assets": [_asset("Setup.exe", EXE)]}
    statuses, ready = run_updater(rel, {"Setup.exe": EXE[:-10]})   # обірване завантаження
    assert ready == []
    assert statuses[-1] == "Помилка перевірки цілісності"


def test_wrong_digest_rejected(run_updater):
    rel = {"tag_name": "v9.9.9", "assets": [_asset("Setup.exe", EXE, digest="sha256:" + "0" * 64)]}
    statuses, ready = run_updater(rel, {"Setup.exe": EXE})
    assert ready == []


def test_missing_checksum_rejected(run_updater):
    rel = {"tag_name": "v9.9.9", "assets": [_asset("Setup.exe", EXE, digest=None)]}
    statuses, ready = run_updater(rel, {"Setup.exe": EXE})
    assert ready == []
    assert statuses[-1] == "Помилка перевірки цілісності"


def test_checksums_file_fallback(run_updater):
    sums = f"{hashlib.sha256(EXE).hexdigest()}  Setup.exe\n".encode()
    rel = {"tag_name": "v9.9.9", "assets": [_asset("Setup.exe", EXE, digest=None),
                                            _asset("SHA256SUMS", sums, digest=None)]}
    statuses, ready = run_updater(rel, {"Setup.exe": EXE, "SHA256SUMS": sums})
    assert ready and updater.is_verified(ready[0][0])


def test_parse_checksums_formats():
    h = "a" * 64
    assert updater.parse_checksums(f"{h}  Setup.exe\n{h.upper()} *dist/firmware.uf2\nnoise") == {
        "setup.exe": h, "firmware.uf2": h}


def test_unverified_path_is_not_trusted(tmp_path):
    p = tmp_path / "random.exe"
    p.write_bytes(b"x")
    assert not updater.is_verified(str(p))
    assert not updater.is_verified("")
