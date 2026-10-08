"""Unit tests run anywhere; the end-to-end test needs the model.

    SITTICH_MODEL_DIR=/pfad/zu/parakeet-primeline-onnx pytest tests
"""

import asyncio
import hashlib
import http.server
import json
import os
import threading
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "sittich"))

from wyoming.asr import Transcribe, Transcript  # noqa: E402
from wyoming.audio import AudioChunk, AudioStart, AudioStop  # noqa: E402
from wyoming.client import AsyncTcpClient  # noqa: E402
from wyoming.info import Describe, Info  # noqa: E402
from wyoming.server import AsyncTcpServer  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402

from wyoming_sittich.__main__ import build_info, configure_logging  # noqa: E402
from wyoming_sittich.handler import MAX_AUDIO_S, SittichEventHandler  # noqa: E402
from wyoming_sittich.hotwords import (  # noqa: E402
    HomeAssistantConnection,
    HotwordSource,
    clean,
)
from wyoming_sittich import model  # noqa: E402
from wyoming_sittich.model import model_installed  # noqa: E402
from wyoming_sittich.recognizer import (  # noqa: E402
    MAX_GAIN,
    SAMPLE_RATE,
    TARGET_PEAK,
    normalize_gain,
    split_audio,
)

MODEL_DIR = Path(os.environ.get("SITTICH_MODEL_DIR", "/nonexistent"))


@pytest.fixture
def model_server(tmp_path, monkeypatch):
    """A local web server with two small stand-in model files."""
    served = tmp_path / "served"
    served.mkdir()
    files = {"a.onnx": b"weights" * 1000, "tokens.txt": b"<blk> 0\n"}
    for name, data in files.items():
        (served / name).write_bytes(data)
    monkeypatch.setattr(
        model,
        "MODEL_FILES",
        {
            name: model.ModelFile(len(data), hashlib.sha256(data).hexdigest())
            for name, data in files.items()
        },
    )

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(served))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield served, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_verifies_and_installs(model_server, tmp_path):
    _, url = model_server
    target = tmp_path / "model"

    model.download_model(target, url)

    assert model_installed(target)
    assert sorted(p.name for p in target.iterdir()) == ["a.onnx", "tokens.txt"]


def test_download_rejects_tampered_file(model_server, tmp_path):
    served, url = model_server
    original = (served / "a.onnx").read_bytes()
    (served / "a.onnx").write_bytes(original[:-1] + b"X")  # same size, other content
    target = tmp_path / "model"

    with pytest.raises(ValueError, match="checksum mismatch"):
        model.download_model(target, url)

    assert list(target.iterdir()) == []  # nothing kept, no .part left behind


def test_download_skips_files_already_there(model_server, tmp_path):
    served, url = model_server
    target = tmp_path / "model"
    model.download_model(target, url)
    (served / "a.onnx").unlink()  # would fail if fetched again

    model.download_model(target, url)

    assert model_installed(target)


def test_pinned_hashes_cover_every_model_file():
    assert set(model.MODEL_FILES) == {
        "encoder.int8.onnx",
        "encoder.int8.onnx.data",
        "decoder.int8.onnx",
        "joiner.int8.onnx",
        "tokens.txt",
        "bpe.vocab",
    }
    assert all(len(f.sha256) == 64 for f in model.MODEL_FILES.values())


def test_split_short_audio_is_untouched():
    audio = np.ones(5 * SAMPLE_RATE, dtype=np.float32)
    pieces = list(split_audio(audio))
    assert len(pieces) == 1 and len(pieces[0]) == len(audio)


def test_split_cuts_long_audio_at_pause():
    rng = np.random.default_rng(0)
    audio = rng.uniform(-0.5, 0.5, 200 * SAMPLE_RATE).astype(np.float32)
    pause = int(85 * SAMPLE_RATE)
    audio[pause : pause + SAMPLE_RATE] = 0.0

    pieces = list(split_audio(audio, max_s=90))

    assert sum(len(p) for p in pieces) == len(audio)
    assert all(len(p) <= 90 * SAMPLE_RATE for p in pieces)
    assert pause <= len(pieces[0]) <= pause + SAMPLE_RATE


def test_gain_raises_quiet_audio_but_is_capped():
    quiet = np.full(100, 0.1, dtype=np.float32)
    assert np.isclose(np.abs(normalize_gain(quiet)).max(), TARGET_PEAK)

    very_quiet = np.full(100, 0.001, dtype=np.float32)
    assert np.isclose(np.abs(normalize_gain(very_quiet)).max(), 0.001 * MAX_GAIN)

    loud = np.full(100, 0.9, dtype=np.float32)
    assert np.array_equal(normalize_gain(loud), loud)


def test_info_announces_german():
    info = build_info()
    assert info.asr[0].models[0].languages == ["de"]


class FakeRecognizer:
    def __init__(self):
        self.received = b""
        self.hotwords = None

    def transcribe(self, pcm: bytes, hotwords=None) -> str:
        self.received = pcm
        self.hotwords = hotwords
        return "Schalte das Licht ein."


class FixedHotwords:
    hotwords = "Deckenlampe/Wohnzimmer"


async def _roundtrip(recognizer, pcm: bytes, rate: int, hotword_source=None) -> tuple[Info, str]:
    server = AsyncTcpServer("127.0.0.1", 0)
    task = asyncio.create_task(
        server.run(partial(SittichEventHandler, build_info(), recognizer, hotword_source))
    )
    while server._server is None:  # noqa: SLF001
        await asyncio.sleep(0.01)
    port = server._server.sockets[0].getsockname()[1]  # noqa: SLF001

    try:
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Describe().event())
            info = Info.from_event(await client.read_event())

        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Transcribe(language="de").event())
            await client.write_event(AudioStart(rate, 2, 1).event())
            for i in range(0, len(pcm), 2048):
                await client.write_event(AudioChunk(rate, 2, 1, pcm[i : i + 2048]).event())
            await client.write_event(AudioStop().event())
            while True:
                event = await client.read_event()
                if Transcript.is_type(event.type):
                    return info, Transcript.from_event(event).text
    finally:
        task.cancel()


def test_handler_resamples_to_16k():
    recognizer = FakeRecognizer()
    pcm = np.zeros(22050, dtype=np.int16).tobytes()  # 1 s at 22.05 kHz

    info, text = asyncio.run(_roundtrip(recognizer, pcm, 22050))

    assert info.asr[0].name == "sittich"
    assert text == "Schalte das Licht ein."
    assert abs(len(recognizer.received) - 2 * SAMPLE_RATE) < 100
    assert recognizer.hotwords is None


def test_handler_passes_hotwords():
    recognizer = FakeRecognizer()
    pcm = np.zeros(16000, dtype=np.int16).tobytes()

    asyncio.run(_roundtrip(recognizer, pcm, 16000, FixedHotwords()))

    assert recognizer.hotwords == "Deckenlampe/Wohnzimmer"


def test_clean_names():
    names = [
        "Wohnzimmer",
        "wohnzimmer",  # duplicate, other case
        "Licht / Flur",  # "/" would split the hotword
        "Gäste-WC",
        "Küche  (Decke)",
        "TV",  # too short
        None,
        "light_kitchen",
    ]
    assert clean(names) == [
        "Wohnzimmer",
        "Licht Flur",
        "Gäste-WC",
        "Küche Decke",
        "light kitchen",
    ]


def test_clean_drops_names_without_letters_and_overlong():
    assert clean(["----", "123", "a" * 61, "Raum 1"]) == ["Raum 1"]


def test_handler_caps_audio_length():
    recognizer = FakeRecognizer()
    pcm = np.zeros(40 * SAMPLE_RATE, dtype=np.int16).tobytes()

    asyncio.run(_roundtrip(recognizer, pcm, SAMPLE_RATE))

    assert len(recognizer.received) == MAX_AUDIO_S * SAMPLE_RATE * 2


def test_token_never_in_debug_log(caplog):
    import logging

    configure_logging(debug=True)
    caplog.set_level(logging.DEBUG)

    hotwords = asyncio.run(_fetch_from_fake("geheim"))

    assert hotwords  # the exchange really happened
    assert "geheim" not in caplog.text


def test_http_url_becomes_websocket_url():
    conn = HomeAssistantConnection.from_http_url("http://ha.local:8123/", "t")
    assert conn.url == "ws://ha.local:8123/api/websocket"
    conn = HomeAssistantConnection.from_http_url("https://ha.example.org", "t")
    assert conn.url == "wss://ha.example.org/api/websocket"


FAKE_HA = {
    "get_states": [
        {"entity_id": "light.decke", "attributes": {"friendly_name": "Wohnzimmer Deckenlampe"}},
        {"entity_id": "light.garten", "attributes": {"friendly_name": "Gartenbeleuchtung"}},
        {"entity_id": "sensor.secret", "attributes": {"friendly_name": "Router Upload"}},
    ],
    "config/entity_registry/get_entries": {
        "light.decke": {"entity_id": "light.decke", "aliases": [None, "Hauptlicht"]},
        "light.garten": None,  # no registry entry
        "sensor.secret": {"entity_id": "sensor.secret", "aliases": ["Geheim"]},
    },
    "config/area_registry/list": [{"area_id": "wz", "name": "Wohnzimmer", "aliases": ["Stube"]}],
    "config/floor_registry/list": [{"floor_id": "eg", "name": "Erdgeschoss", "aliases": []}],
    "homeassistant/expose_entity/list": {
        "exposed_entities": {
            "light.decke": {"conversation": True},
            "light.garten": {"conversation": True},
            "sensor.secret": {"conversation": False},
        }
    },
}


async def _fake_home_assistant(ws):
    await ws.send(json.dumps({"type": "auth_required"}))
    auth = json.loads(await ws.recv())
    if auth.get("access_token") != "geheim":
        await ws.send(json.dumps({"type": "auth_invalid"}))
        return
    await ws.send(json.dumps({"type": "auth_ok"}))
    async for raw in ws:
        msg = json.loads(raw)
        result = FAKE_HA[msg["type"]]
        if msg["type"] == "config/entity_registry/get_entries":
            result = {eid: result.get(eid) for eid in msg["entity_ids"]}
        await ws.send(
            json.dumps({"id": msg["id"], "type": "result", "success": True, "result": result})
        )


async def _fetch_from_fake(token: str):
    async with serve(_fake_home_assistant, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        conn = HomeAssistantConnection(f"ws://127.0.0.1:{port}/api/websocket", token)
        source = HotwordSource(conn)
        await source.refresh()
        return source.hotwords


def test_names_from_home_assistant_only_exposed():
    hotwords = asyncio.run(_fetch_from_fake("geheim"))
    assert hotwords.split("/") == [
        "Wohnzimmer",
        "Stube",
        "Erdgeschoss",
        "Wohnzimmer Deckenlampe",
        "Gartenbeleuchtung",
        "Hauptlicht",
    ]


async def _silent_home_assistant(ws):
    """Accepts the connection, then never answers (e.g. while HA restarts)."""
    await ws.wait_closed()


def test_hotword_refresh_gives_up_after_timeout():
    async def run():
        async with serve(_silent_home_assistant, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            conn = HomeAssistantConnection(f"ws://127.0.0.1:{port}/api/websocket", "x")
            source = HotwordSource(conn, timeout_s=0.5)
            started = asyncio.get_running_loop().time()
            ok = await source.refresh()
            return ok, asyncio.get_running_loop().time() - started, source.hotwords

    ok, elapsed, hotwords = asyncio.run(run())
    assert ok is False and hotwords is None
    assert elapsed < 3


def test_older_home_assistant_without_floors_and_get_entries(monkeypatch):
    """Commands unknown to older versions only drop their part of the names."""
    old = dict(FAKE_HA)
    del old["config/floor_registry/list"]
    del old["config/entity_registry/get_entries"]
    monkeypatch.setattr(sys.modules[__name__], "FAKE_HA", old)

    async def unknown_command_tolerant(ws):
        await ws.send(json.dumps({"type": "auth_required"}))
        await ws.recv()
        await ws.send(json.dumps({"type": "auth_ok"}))
        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] not in old:
                reply = {"id": msg["id"], "type": "result", "success": False,
                         "error": {"code": "unknown_command", "message": "Unknown command."}}
            else:
                reply = {"id": msg["id"], "type": "result", "success": True, "result": old[msg["type"]]}
            await ws.send(json.dumps(reply))

    async def run():
        async with serve(unknown_command_tolerant, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            source = HotwordSource(HomeAssistantConnection(f"ws://127.0.0.1:{port}/api/websocket", "x"))
            assert await source.refresh()
            return source.hotwords.split("/")

    names = asyncio.run(run())
    assert "Wohnzimmer Deckenlampe" in names and "Stube" in names
    assert "Erdgeschoss" not in names and "Hauptlicht" not in names


def test_failed_refresh_retries_sooner():
    calls = []

    class Source(HotwordSource):
        async def refresh(self):
            calls.append(asyncio.get_running_loop().time())
            return len(calls) > 1  # first attempt fails

    async def run():
        source = Source(HomeAssistantConnection("ws://unused", "x"), refresh_s=60, retry_s=0.05)
        task = asyncio.create_task(source.run(last_ok=False))
        await asyncio.sleep(0.3)
        task.cancel()

    asyncio.run(run())
    assert len(calls) == 2  # retried after 0.05 s, then waits the full 60 s


def test_regional_language_codes_do_not_warn(caplog):
    import logging

    caplog.set_level(logging.WARNING)

    async def send(language):
        server = AsyncTcpServer("127.0.0.1", 0)
        task = asyncio.create_task(server.run(partial(SittichEventHandler, build_info(), FakeRecognizer(), None)))
        while server._server is None:  # noqa: SLF001
            await asyncio.sleep(0.01)
        port = server._server.sockets[0].getsockname()[1]  # noqa: SLF001
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Transcribe(language=language).event())
            await client.write_event(AudioStart(16000, 2, 1).event())
            await client.write_event(AudioStop().event())
            await client.read_event()
        task.cancel()

    for language in ("de", "de-DE", "de-CH"):
        asyncio.run(send(language))
    assert "only knows German" not in caplog.text
    asyncio.run(send("en-US"))
    assert "only knows German" in caplog.text


def test_wrong_token_keeps_hotwords_off():
    assert asyncio.run(_fetch_from_fake("falsch")) is None


@pytest.mark.skipif(
    not model_installed(MODEL_DIR) or "SITTICH_TEST_WAV" not in os.environ,
    reason="SITTICH_MODEL_DIR / SITTICH_TEST_WAV not set",
)
def test_real_model_transcribes_speech():
    import wave

    from wyoming_sittich.recognizer import Recognizer

    wav_path = Path(os.environ["SITTICH_TEST_WAV"])
    with wave.open(str(wav_path)) as wav:
        rate, pcm = wav.getframerate(), wav.readframes(wav.getnframes())

    _, text = asyncio.run(_roundtrip(Recognizer(MODEL_DIR, 4), pcm, rate))

    assert text.strip(), "empty transcript"
    expected = os.environ.get("SITTICH_TEST_TEXT")
    if expected:
        assert expected.lower() in text.lower()


HOTWORD_WAV = Path(os.environ.get("SITTICH_HOTWORD_WAV", "/nonexistent"))
HOTWORD = os.environ.get("SITTICH_HOTWORD", "")


@pytest.mark.skipif(
    not model_installed(MODEL_DIR) or not HOTWORD_WAV.is_file() or not HOTWORD,
    reason="SITTICH_MODEL_DIR / SITTICH_HOTWORD_WAV / SITTICH_HOTWORD not set",
)
def test_real_model_hotwords_fix_misheard_name():
    """A recording whose name the model gets wrong on its own, e.g.

    SITTICH_HOTWORD_WAV=aufnahme.wav SITTICH_HOTWORD=Gartenbeleuchtung
    """
    import wave

    from wyoming_sittich.recognizer import Recognizer

    with wave.open(str(HOTWORD_WAV)) as wav:
        rate, pcm = wav.getframerate(), wav.readframes(wav.getnframes())
    hotwords = FixedHotwords()
    hotwords.hotwords = f"{HOTWORD}/Wohnzimmerlampe/Deckenlampe"

    _, plain = asyncio.run(_roundtrip(Recognizer(MODEL_DIR, 4), pcm, rate))
    _, biased = asyncio.run(
        _roundtrip(Recognizer(MODEL_DIR, 4, hotwords=True), pcm, rate, hotwords)
    )

    assert HOTWORD not in plain
    assert HOTWORD in biased
