"""Wyoming speech-to-text server for German, backed by parakeet-primeline."""

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import urllib.request
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

from wyoming.info import AsrModel, AsrProgram, Attribution, Info
from wyoming.server import AsyncServer

from . import __version__
from .handler import LANGUAGE, SittichEventHandler
from .hotwords import HomeAssistantConnection, HotwordSource
from .model import MODEL_NAME, MODEL_REPO, ensure_model
from .recognizer import Recognizer

_LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wyoming-sittich")
    parser.add_argument("--uri", default="tcp://0.0.0.0:10300")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("/app/model"),
        help="Where the model lives (built into the image); downloaded if missing",
    )
    parser.add_argument(
        "--threads", type=int, default=4, help="CPU threads used for decoding"
    )
    parser.add_argument(
        "--ha-url",
        default=os.environ.get("HA_URL"),
        help="Home Assistant URL, e.g. http://192.168.1.10:8123 (for hotwords); "
        "the access token is read from HA_TOKEN only, never from the command line, "
        "where other users could see it",
    )
    parser.add_argument(
        "--no-hotwords",
        dest="hotwords",
        action="store_false",
        help="Do not bias recognition towards names from Home Assistant",
    )
    parser.add_argument("--hotwords-score", type=float, default=2.0)
    parser.add_argument(
        "--zeroconf",
        nargs="?",
        const="sittich",
        help="Announce via mDNS so Home Assistant finds the server (optional name)",
    )
    parser.add_argument(
        "--options",
        type=Path,
        default=Path("/data/options.json"),
        help="Add-on options file; if present its values override the arguments",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.options.is_file():
        options = json.loads(args.options.read_text())
        args.threads = int(options.get("threads", args.threads))
        args.debug = bool(options.get("debug", args.debug))
        args.hotwords = bool(options.get("hotwords", args.hotwords))
        args.hotwords_score = float(options.get("hotwords_score", args.hotwords_score))

    return args


def build_info() -> Info:
    return Info(
        asr=[
            AsrProgram(
                name="sittich",
                description="German speech-to-text with parakeet-primeline (CPU, offline)",
                attribution=Attribution(
                    name="k2-fsa/sherpa-onnx",
                    url="https://github.com/k2-fsa/sherpa-onnx",
                ),
                installed=True,
                version=__version__,
                models=[
                    AsrModel(
                        name=MODEL_NAME,
                        description="German fine-tune of nvidia/parakeet-tdt-0.6b-v3 (int8)",
                        attribution=Attribution(
                            name="primeLine, NVIDIA (CC-BY-4.0)",
                            url=f"https://huggingface.co/{MODEL_REPO}",
                        ),
                        installed=True,
                        languages=[LANGUAGE],
                        version=None,
                    )
                ],
            )
        ],
    )


def home_assistant_connection(args: argparse.Namespace) -> HomeAssistantConnection | None:
    if supervisor_token := os.environ.get("SUPERVISOR_TOKEN"):
        return HomeAssistantConnection("ws://supervisor/core/websocket", supervisor_token)
    token = os.environ.get("HA_TOKEN")
    if args.ha_url and token:
        return HomeAssistantConnection.from_http_url(args.ha_url, token)
    if args.ha_url or token:
        _LOGGER.warning("Hotwords need both --ha-url and HA_TOKEN")
    return None


def register_with_supervisor(port: int) -> None:
    """Tell Home Assistant about this add-on so the Wyoming integration shows up."""
    token = os.environ["SUPERVISOR_TOKEN"]
    body = json.dumps(
        {
            "service": "wyoming",
            "config": {"uri": f"tcp://{socket.gethostname()}:{port}"},
        }
    ).encode()
    request = urllib.request.Request(
        "http://supervisor/discovery",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
        _LOGGER.info("Registered with Home Assistant")
    except OSError as err:
        _LOGGER.warning("Home Assistant discovery failed: %s", err)


def configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # At debug level websockets logs every frame, including the access token.
    logging.getLogger("websockets").setLevel(logging.INFO)


async def main() -> None:
    args = parse_args()
    configure_logging(args.debug)

    ensure_model(args.model_dir)
    hotword_source = None
    first_refresh_ok = False
    if args.hotwords and (conn := home_assistant_connection(args)):
        hotword_source = HotwordSource(conn)
        first_refresh_ok = await hotword_source.refresh()
    elif args.hotwords:
        _LOGGER.info("No Home Assistant connection configured, hotwords off")

    _LOGGER.info("Loading model with %d threads", args.threads)
    recognizer = Recognizer(
        args.model_dir,
        args.threads,
        hotwords=hotword_source is not None,
        hotwords_score=args.hotwords_score,
    )

    server = AsyncServer.from_uri(args.uri)
    port = urlparse(args.uri).port or 10300
    await server.start(
        partial(SittichEventHandler, build_info(), recognizer, hotword_source)
    )
    _LOGGER.info("Ready on %s", args.uri)

    # Announce only now that the port is open, so Home Assistant can connect.
    # Only set when running as a Home Assistant add-on:
    if os.environ.get("SUPERVISOR_TOKEN"):
        await asyncio.to_thread(register_with_supervisor, port)
    # Keep the announcement referenced for as long as the server runs.
    announcement = await announce_zeroconf(args.zeroconf, port) if args.zeroconf else None

    # Keep a reference so the task is not garbage collected.
    refresh_task = (
        asyncio.create_task(hotword_source.run(last_ok=first_refresh_ok))
        if hotword_source
        else None
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    _LOGGER.info("Stopping")
    if refresh_task:
        refresh_task.cancel()
    await server.stop()
    if announcement is not None:
        # Says goodbye on the network, so the entry disappears right away.
        await announcement._aiozc.async_close()  # noqa: SLF001 - no public API


async def announce_zeroconf(name: str, port: int):
    from wyoming.zeroconf import HomeAssistantZeroconf

    try:
        announcement = HomeAssistantZeroconf(name=name, port=port)
        await announcement.register_server()
        _LOGGER.info("Announced via zeroconf as %r", name)
        return announcement
    except Exception as err:  # noqa: BLE001 - serving matters more than announcing
        # E.g. another server already uses this name on the network.
        _LOGGER.warning(
            "Zeroconf announcement as %r failed (%r); the server still runs, "
            "add it in Home Assistant by IP address",
            name,
            err,
        )
        return None


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
