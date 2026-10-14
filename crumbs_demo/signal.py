"""DNS steering, as a demo: the Crumbs answer that carries an opted-in interest group.

The Crumbs resolver can only answer a lookup with an address. To carry a group,
each group gets its own address. When a Crumbs-on lane looks up the signal
hostname, the filter answers with the address for the chosen group. The page
can't read that address, so the Crumbs Prebid module makes a small request to
the hostname, and this server (standing in for Crumbs or a partner SSP) replies
with the group it was reached on. The module then puts the group into the bid
request as a seller-defined audience (IAB Audience Taxonomy 1.1, segtax 4).

Lanes with Crumbs off get no answer for the hostname, so the module does nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("crumbs.signal")

SEGTAX_AUDIENCE_1_1 = 4

# IDs are real IAB Audience Taxonomy 1.1 nodes.
DEFAULT_GROUPS = [
    {"key": "running", "label": "Running and jogging", "taxonomy": "Interest | Healthy Living | Running and Jogging", "id": 410},
    {"key": "finance", "label": "Personal finance", "taxonomy": "Interest | Personal Finance", "id": 534},
    {"key": "travel", "label": "Travel", "taxonomy": "Interest | Travel", "id": 719},
    {"key": "cooking", "label": "Cooking", "taxonomy": "Interest | Food & Drink | Cooking", "id": 371},
    {"key": "gaming", "label": "Video gaming", "taxonomy": "Interest | Video Gaming", "id": 733},
]
NO_GROUP_ADDR = "127.0.0.19"


class Signal:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.host = cfg.get("host", "signal.crumbs.test").lower()
        self.port = int(cfg.get("port", 5390))
        self.provider = cfg.get("provider", "crumbs.com")
        self.groups = cfg.get("groups") or DEFAULT_GROUPS
        for i, g in enumerate(self.groups):
            g.setdefault("addr", f"127.0.0.{20 + i}")
        self.group = cfg.get("group", self.groups[0]["key"])  # "" means opted out
        self.errors: list[str] = []

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/group"

    def by_key(self, key: str) -> dict | None:
        return next((g for g in self.groups if g["key"] == key), None)

    def address(self) -> str:
        g = self.by_key(self.group)
        return g["addr"] if g else NO_GROUP_ADDR

    def set_group(self, key: str) -> None:
        if key and not self.by_key(key):
            raise ValueError(f"unknown group {key!r}")
        self.group = key

    def answer_for(self, local_addr: str) -> dict:
        """What the server says to a request that arrived on local_addr."""
        g = next((g for g in self.groups if g["addr"] == local_addr), None)
        body = {"crumbs": "on", "arrived_on": local_addr, "provider": self.provider, "group": None}
        if g:
            body.update(group=g["key"], label=g["label"], taxonomy=g["taxonomy"],
                        sda={"segtax": SEGTAX_AUDIENCE_1_1, "id": str(g["id"])})
        return body

    def to_dict(self) -> dict:
        return {"host": self.host, "port": self.port, "group": self.group, "provider": self.provider,
                "groups": [{k: g[k] for k in ("key", "label", "taxonomy", "id", "addr")} for g in self.groups],
                "errors": self.errors}

    async def start(self) -> list:
        servers = []
        for addr in [NO_GROUP_ADDR] + [g["addr"] for g in self.groups]:
            try:
                servers.append(await asyncio.start_server(self._client, addr, self.port))
            except OSError as e:
                self.errors.append(f"{addr}:{self.port} ({e.strerror or e})")
        if self.errors:
            log.warning("signal server could not listen on: %s", ", ".join(self.errors))
        return servers

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            method = head.split(b" ", 1)[0].decode("latin-1").upper()
            local = writer.get_extra_info("sockname")[0]
            payload = b"" if method == "OPTIONS" else json.dumps(self.answer_for(local)).encode()
            writer.write(
                b"HTTP/1.1 " + (b"204 No Content" if method == "OPTIONS" else b"200 OK") + b"\r\n"
                b"Content-Type: application/json\r\nCache-Control: no-store\r\n"
                b"Access-Control-Allow-Origin: *\r\nAccess-Control-Allow-Private-Network: true\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            pass
        finally:
            writer.close()
