"""Hotwords from Home Assistant: names of exposed entities, aliases, areas, floors.

These bias the recognizer towards words that actually exist in the home, so
long or unusual device names come out spelled the way they are in Home
Assistant.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from websockets.asyncio.client import connect

_LOGGER = logging.getLogger(__name__)

MIN_LENGTH = 3
MAX_LENGTH = 60
MAX_HOTWORDS = 1000
FETCH_TIMEOUT_S = 30  # Home Assistant may accept the connection but not answer
RETRY_S = 30  # after a failed refresh, e.g. while Home Assistant restarts
# "/" separates hotwords for sherpa-onnx; anything but letters, digits,
# spaces and hyphens would only confuse the BPE encoder.
_UNWANTED = re.compile(r"[^\w\s-]|_")


@dataclass(frozen=True)
class HomeAssistantConnection:
    url: str  # e.g. ws://homeassistant.local:8123/api/websocket
    token: str

    @staticmethod
    def from_http_url(url: str, token: str) -> "HomeAssistantConnection":
        url = url.rstrip("/")
        if url.startswith("http"):
            url = "ws" + url[len("http") :]
        if not url.endswith("/websocket"):
            url += "/api/websocket"
        return HomeAssistantConnection(url, token)


def clean(names: Iterable[Any]) -> list[str]:
    """Drop junk and duplicates (case-insensitive), keep the first spelling."""
    seen: set[str] = set()
    result = []
    for name in names:
        if not isinstance(name, str):
            continue
        name = " ".join(_UNWANTED.sub(" ", name).split())
        key = name.casefold()
        if (
            not MIN_LENGTH <= len(name) <= MAX_LENGTH
            or not any(c.isalpha() for c in name)
            or key in seen
        ):
            continue
        seen.add(key)
        result.append(name)
    return result[:MAX_HOTWORDS]


async def fetch_names(conn: HomeAssistantConnection) -> list[str]:
    async with connect(conn.url, max_size=None, open_timeout=10) as ws:
        message = json.loads(await ws.recv())
        if message.get("type") != "auth_required":
            raise ConnectionError(f"Unexpected greeting: {message}")
        await ws.send(json.dumps({"type": "auth", "access_token": conn.token}))
        message = json.loads(await ws.recv())
        if message.get("type") != "auth_ok":
            raise PermissionError("Home Assistant rejected the access token")

        next_id = 0

        async def call(command: str, **data: Any) -> Any:
            nonlocal next_id
            next_id += 1
            await ws.send(json.dumps({"id": next_id, "type": command, **data}))
            while True:
                reply = json.loads(await ws.recv())
                if reply.get("id") == next_id:
                    break
            if not reply.get("success"):
                raise RuntimeError(f"{command} failed: {reply.get('error')}")
            return reply["result"]

        async def optional_call(command: str, default: Any, **data: Any) -> Any:
            """Commands that older Home Assistant versions do not know."""
            try:
                return await call(command, **data)
            except RuntimeError as err:
                _LOGGER.debug("Skipping %s: %s", command, err)
                return default

        states = await call("get_states")
        areas = await call("config/area_registry/list")
        floors = await optional_call("config/floor_registry/list", [])  # HA 2024.4+
        try:
            exposed_settings = (await call("homeassistant/expose_entity/list"))[
                "exposed_entities"
            ]
            exposed = {
                entity_id
                for entity_id, settings in exposed_settings.items()
                if settings.get("conversation")
            }
        except (RuntimeError, KeyError) as err:
            _LOGGER.warning("Cannot tell which entities Assist sees (%s), using all", err)
            exposed = {state["entity_id"] for state in states}

        # The registry list leaves out aliases (HA 2026.10); get_entries has
        # them. An alias of None stands for the entity's own name.
        entries = await optional_call(
            "config/entity_registry/get_entries", {}, entity_ids=sorted(exposed)
        )

    names: list[Any] = []
    names += [area["name"] for area in areas]
    names += [alias for area in areas for alias in area.get("aliases") or []]
    names += [floor["name"] for floor in floors]
    names += [alias for floor in floors for alias in floor.get("aliases") or []]
    names += [
        state["attributes"].get("friendly_name")
        for state in states
        if state["entity_id"] in exposed
    ]
    names += [
        alias
        for entry in entries.values()
        if entry  # None for entities without a registry entry
        for alias in entry.get("aliases") or []
    ]
    return clean(names)


class HotwordSource:
    """Keeps an up-to-date hotword list, refreshed in the background."""

    def __init__(
        self,
        conn: HomeAssistantConnection,
        refresh_s: float = 300,
        retry_s: float = RETRY_S,
        timeout_s: float = FETCH_TIMEOUT_S,
    ) -> None:
        self._conn = conn
        self._refresh_s = refresh_s
        self._retry_s = retry_s
        self._timeout_s = timeout_s
        self._names: list[str] = []
        self.hotwords: Optional[str] = None

    async def refresh(self) -> bool:
        """Load the names; on failure keep the previous list. Returns success."""
        try:
            async with asyncio.timeout(self._timeout_s):
                names = await fetch_names(self._conn)
        except Exception as err:  # noqa: BLE001 - keep the old list on any failure
            _LOGGER.warning("Could not load names from Home Assistant: %r", err)
            return False
        if names != self._names:
            _LOGGER.info("Loaded %d hotwords from Home Assistant", len(names))
            _LOGGER.debug("Hotwords: %s", names)
        self._names = names
        self.hotwords = "/".join(names) or None
        return True

    async def run(self, last_ok: bool = True) -> None:
        """Refresh periodically; call refresh() once before for the first list."""
        while True:
            await asyncio.sleep(self._refresh_s if last_ok else self._retry_s)
            last_ok = await self.refresh()
