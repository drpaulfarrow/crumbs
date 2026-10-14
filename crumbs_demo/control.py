"""Control panel, JSON API and the Prebid test page, on one small local web server."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .blocklist import PACKAGE_DIR
from .engine import Engine
from .launcher import warm_profile_state
from .logos import get_logo, logo_map
from .system_dns import run_elevated, system_dns_state

log = logging.getLogger("crumbs.control")

STATIC_DIR = PACKAGE_DIR / "static"
REPO_DIR = PACKAGE_DIR.parent
CONFIG_FILE = REPO_DIR / "demo_config.json"
CONFIG_EXAMPLE = REPO_DIR / "demo_config.example.json"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
}
STATIC_ROUTES = {
    "/": "index.html",
    "/test": "testpage.html",
    "/test/": "testpage.html",
    "/case-study": "case-study.html",
    "/case-study/": "case-study.html",
}


def flush_os_dns_cache() -> None:
    if os.name == "nt":
        subprocess.Popen(["ipconfig", "/flushdns"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_demo_config() -> dict:
    path = CONFIG_FILE if CONFIG_FILE.exists() else CONFIG_EXAMPLE
    return json.loads(path.read_text(encoding="utf-8"))


class ControlServer:
    def __init__(self, engine: Engine, port: int, launcher=None, bind: str = "127.0.0.1", warmup=None):
        self.engine = engine
        self.warmup = warmup
        self.port = port
        self.bind = bind
        self.launcher = launcher
        system = engine.lanes.get("system")
        if system:
            system.on_toggle.append(lambda _lane: flush_os_dns_cache())

    async def start(self):
        return await asyncio.start_server(self._client, self.bind, self.port)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            length = int(headers.get("content-length", "0") or 0)
            body = await reader.readexactly(length) if length else b""
            peer = writer.get_extra_info("peername")
            status, ctype, payload = await self.route(method, target, body, headers, peer)
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(payload)}\r\n"
                f"Cache-Control: {'max-age=86400' if target.startswith('/logo/') else 'no-store'}\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Connection: close\r\n\r\n".encode() + payload)
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    def _json(self, data, status="200 OK"):
        return status, CONTENT_TYPES[".json"], json.dumps(data).encode()

    async def route(self, method: str, target: str, body: bytes, headers: dict, peer):
        url = urlsplit(target)
        path = url.path
        if method == "OPTIONS":
            return "204 No Content", "text/plain", b""

        if method == "GET" and path in STATIC_ROUTES:
            return self._static(STATIC_ROUTES[path])
        if method == "GET" and path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if method == "GET" and path == "/api/state":
            state = self.engine.state()
            state["system_dns"] = system_dns_state()
            state["warm_profile"] = warm_profile_state()
            return self._json(state)
        if method == "GET" and path == "/api/verdicts":
            # What the lane decided per hostname, so the test page can say
            # "blocked by Crumbs" only when Crumbs really blocked it.
            lane = self.engine.lanes.get(parse_qs(url.query).get("lane", [""])[0])
            return self._json(lane.stats.last_verdict if lane else {})
        if method == "POST" and path in ("/api/system-dns/on", "/api/system-dns/off"):
            try:
                run_elevated(path.endswith("/on"))
            except Exception as e:
                return self._json({"error": str(e)}, "500 Internal Server Error")
            return self._json({"ok": True})
        if method == "GET" and path.startswith("/logo/"):
            ctype, data = await asyncio.get_running_loop().run_in_executor(None, get_logo, path[len("/logo/"):])
            return "200 OK", ctype, data
        if method == "GET" and path == "/api/logo-map":
            return self._json(logo_map())
        if method == "GET" and path == "/api/demo-config":
            return self._json(load_demo_config())

        if method == "POST" and path.startswith("/api/lanes/"):
            name = path.rsplit("/", 1)[-1]
            if name not in self.engine.lanes:
                return self._json({"error": "unknown lane"}, "404 Not Found")
            enabled = bool(json.loads(body or b"{}").get("enabled"))
            return self._json(self.engine.set_enabled(name, enabled).to_dict())
        if method == "POST" and path in ("/api/policy", "/api/module"):
            enabled = bool(json.loads(body or b"{}").get("enabled"))
            if path == "/api/policy":
                self.engine.policy_fix = enabled
                for lane in self.engine.lanes.values():  # reconnect so open tunnels follow the new policy
                    for callback in lane.on_toggle:
                        callback(lane)
            else:
                self.engine.inject_module = enabled
            return self._json({"ok": True, "enabled": enabled})
        if method == "POST" and path == "/api/signal":
            if not self.engine.signal:
                return self._json({"error": "signal unavailable"}, "500 Internal Server Error")
            try:
                self.engine.signal.set_group(json.loads(body or b"{}").get("group", ""))
            except ValueError as e:
                return self._json({"error": str(e)}, "400 Bad Request")
            return self._json(self.engine.signal.to_dict())
        if method == "POST" and path == "/api/reset":
            self.engine.reset_stats()
            return self._json({"ok": True})
        if method == "POST" and path == "/api/launch":
            if not self.launcher:
                return self._json({"error": "launcher unavailable"}, "500 Internal Server Error")
            opts = parse_qs(url.query)
            try:
                warm = opts.get("warm", [None])[0]
                kwargs = {"page": opts.get("page", ["site"])[0],
                          "warm": None if warm is None else warm == "1"}
                if opts.get("beside", ["0"])[0] == "1":
                    kwargs["beside"] = True
                started = self.launcher(**kwargs)
            except Exception as e:  # surfaced in the panel
                return self._json({"error": str(e)}, "500 Internal Server Error")
            return self._json({"ok": True, "started": started})
        if method == "POST" and path == "/api/warmup":
            if not self.warmup:
                return self._json({"error": "warm-up unavailable"}, "500 Internal Server Error")
            try:
                self.warmup()
            except Exception as e:
                return self._json({"error": str(e)}, "500 Internal Server Error")
            return self._json({"ok": True})
        if method == "POST" and path == "/api/page-event":
            event = json.loads(body or b"{}")
            event["t"] = time.time()
            event["peer"] = peer[0] if peer else None
            event["user_agent"] = headers.get("user-agent", "")
            self.engine.page_events.append(event)
            return self._json({"ok": True})
        return self._json({"error": "not found"}, "404 Not Found")

    def _static(self, rel: str):
        path = (STATIC_DIR / rel).resolve()
        if STATIC_DIR.resolve() not in path.parents or not path.is_file():
            return "404 Not Found", "text/plain", b"not found"
        ctype = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        return "200 OK", ctype, path.read_bytes()
