"""Per-window lanes: a tiny HTTP proxy whose name resolution goes through the Crumbs filter.

Each browser window is launched with --proxy-server pointing at its own lane,
so the browser never resolves names itself: every hostname arrives here, is
checked against the block list, and is resolved via upstream DNS. HTTPS stays
end-to-end encrypted (CONNECT tunnel); the proxy only sees hostnames, which is
exactly what a DNS filter sees.
"""

from __future__ import annotations

import asyncio
import logging

from .engine import Engine, Lane

log = logging.getLogger("crumbs.proxy")

MAX_HEAD = 64 * 1024
CONNECT_TIMEOUT = 10


def _parse_target(method: str, target: str) -> tuple[str, int, str | None]:
    """Return (host, port, origin-form path or None for CONNECT)."""
    if method == "CONNECT":
        host, _, port = target.rpartition(":")
        return host.strip("[]"), int(port or 443), None
    if not target.lower().startswith("http://"):
        raise ValueError("only absolute http:// URLs are proxied")
    rest = target[7:]
    authority, slash, path = rest.partition("/")
    host, _, port = authority.rpartition(":") if authority.count(":") == 1 else (authority, "", "")
    return host.strip("[]"), int(port or 80), slash + path or "/"


class LaneProxy:
    def __init__(self, engine: Engine, lane: Lane, bind: str = "127.0.0.1"):
        self.engine = engine
        self.lane = lane
        self.bind = bind
        self.server: asyncio.base_events.Server | None = None
        self.connections: set[asyncio.StreamWriter] = set()
        lane.on_toggle.append(lambda _lane: self.drop_connections())

    async def start(self) -> None:
        try:
            self.server = await asyncio.start_server(self._client, self.bind, self.lane.port)
            self.lane.running = True
        except OSError as e:
            self.lane.error = f"{self.bind}:{self.lane.port} ({e.strerror or e})"

    def drop_connections(self) -> None:
        """Close open tunnels so a toggle applies to already-open connections too."""
        for writer in list(self.connections):
            writer.close()
        self.connections.clear()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.connections.add(writer)
        remote_writer = None
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            if len(head) > MAX_HEAD:
                return
            lines = head.decode("latin-1").split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            host, port, path = _parse_target(method.upper(), target)

            decision, result = await self.engine.resolve(self.lane, host)
            if decision.blocked:
                await self._refuse(writer, decision.rule or decision.source)
                return
            ips = result.ips if result else []
            if not ips:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return

            remote_reader = None
            for ip in ips:
                try:
                    remote_reader, remote_writer = await asyncio.wait_for(
                        asyncio.open_connection(ip, port), CONNECT_TIMEOUT)
                    break
                except (OSError, asyncio.TimeoutError):
                    continue
            if remote_writer is None:
                writer.write(b"HTTP/1.1 504 Gateway Timeout\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            self.connections.add(remote_writer)

            if path is None:
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                headers = [h for h in lines[1:] if h and not h.lower().startswith(
                    ("proxy-connection:", "connection:", "keep-alive:"))]
                request = "\r\n".join([f"{method} {path} {version}", *headers, "Connection: close", "", ""])
                remote_writer.write(request.encode("latin-1"))
                self.lane.stats.bytes_up += len(request)

            await asyncio.gather(
                self._pipe(reader, remote_writer, up=True),
                self._pipe(remote_reader, writer, up=False),
            )
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, ConnectionError):
            pass
        except Exception:
            log.exception("proxy error on lane %s", self.lane.name)
        finally:
            for w in (writer, remote_writer):
                if w is not None:
                    self.connections.discard(w)
                    w.close()

    async def _refuse(self, writer: asyncio.StreamWriter, rule: str | None) -> None:
        writer.write(
            b"HTTP/1.1 403 Forbidden\r\nX-Crumbs-Blocked: " + (rule or "").encode() +
            b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        await writer.drain()

    async def _pipe(self, src: asyncio.StreamReader, dst: asyncio.StreamWriter, up: bool):
        try:
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    break
                if up:
                    self.lane.stats.bytes_up += len(chunk)
                else:
                    self.lane.stats.bytes_down += len(chunk)
                dst.write(chunk)
                await dst.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            if dst.can_write_eof():
                try:
                    dst.write_eof()
                except OSError:
                    pass
