"""Watch what each A/B window actually does, via the Chrome DevTools Protocol.

The lane proxy only sees hostnames. This sees the browser's side: which page
each tab is on, and every request with its full URL and outcome, including
requests the browser stopped itself (e.g. Edge tracking prevention) that never
reach the proxy.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
import urllib.request
from collections import deque
from urllib.parse import urlsplit

import websockets

log = logging.getLogger("crumbs.browser")

# Chrome's error text -> what it means in this demo.
ERROR_LABELS = {
    "net::ERR_TUNNEL_CONNECTION_FAILED": "blocked by Crumbs",
    "net::ERR_BLOCKED_BY_CLIENT": "blocked by the browser itself",
    "net::ERR_BLOCKED_BY_RESPONSE": "blocked by the browser itself",
    "net::ERR_NAME_NOT_RESOLVED": "DNS lookup failed",
    "net::ERR_ABORTED": "cancelled by the page",
    "net::ERR_CONNECTION_REFUSED": "connection refused",
    "net::ERR_CONNECTION_TIMED_OUT": "timed out",
    "net::ERR_TIMED_OUT": "timed out",
    "net::ERR_PROXY_CONNECTION_FAILED": "demo proxy not running",
    "net::ERR_EMPTY_RESPONSE": "connection dropped",
    "net::ERR_CONNECTION_CLOSED": "connection dropped",
    "net::ERR_CONNECTION_RESET": "connection dropped",
}


def outcome_for(error_text: str | None, blocked_reason: str | None) -> str:
    if blocked_reason:
        return "blocked by the browser itself"
    return ERROR_LABELS.get(error_text or "", error_text or "failed")


class LaneMonitor:
    def __init__(self, lane, cdp_port: int):
        self.lane = lane
        self.cdp_port = cdp_port
        self.connected = False
        self.tabs: dict[str, dict] = {}
        self.requests: deque = deque(maxlen=300)
        self.counts = {"ok": 0, "crumbs": 0, "browser": 0, "other": 0}
        self._pending: dict[tuple, dict] = {}
        self._ids = itertools.count(1)
        self._ws = None
        self._task: asyncio.Task | None = None
        self._queued: list[str] = []
        self._bounds: dict | None = None
        self._calls: dict[int, asyncio.Future] = {}

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    def open_urls(self, urls: list[str], bounds: dict | None = None) -> None:
        """Open tabs once attached, so their very first requests are captured.

        bounds places the window ({left, top, width, height} in the browser's
        own units), which is reliable whatever the Windows display scaling.
        """
        self._queued = list(urls)
        self._bounds = bounds
        if self.connected:
            asyncio.ensure_future(self._open_queued())

    async def _open_queued(self) -> None:
        urls, self._queued = self._queued, []
        if not urls:
            return
        first = None
        for url in urls:
            reply = await self._call("Target.createTarget", {"url": url})
            first = first or (reply or {}).get("result", {}).get("targetId")
        await asyncio.sleep(0.8)
        for target_id, tab in list(self.tabs.items()):
            if tab.get("url") in ("about:blank", "") or tab.get("url", "").startswith(("chrome://newtab", "edge://newtab")):
                await self._send("Target.closeTarget", {"targetId": target_id})
        if first and self._bounds:
            await self._place_window(first, self._bounds)

    async def _place_window(self, target_id: str, bounds: dict) -> None:
        reply = await self._call("Browser.getWindowForTarget", {"targetId": target_id})
        window_id = (reply or {}).get("result", {}).get("windowId")
        if window_id is None:
            return
        # A maximised or minimised window ignores size changes until it's normal.
        await self._call("Browser.setWindowBounds", {"windowId": window_id, "bounds": {"windowState": "normal"}})
        await self._call("Browser.setWindowBounds", {"windowId": window_id, "bounds": dict(bounds)})

    async def _call(self, method: str, params: dict | None = None, timeout: float = 5.0) -> dict | None:
        """Send a command and wait for its reply. Not for use inside _handle."""
        if not self._ws:
            return None
        msg_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._calls[msg_id] = future
        await self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._calls.pop(msg_id, None)

    def reset(self) -> None:
        self.requests.clear()
        self._pending.clear()
        self.counts = {k: 0 for k in self.counts}

    def to_dict(self) -> dict:
        return {
            "connected": self.connected,
            "cdp_port": self.cdp_port,
            "tabs": [t for t in self.tabs.values() if t.get("type") == "page"],
            "counts": self.counts,
            "requests": list(self.requests)[::-1][:80],
        }

    async def _run(self) -> None:
        while True:
            try:
                ws_url = await asyncio.get_running_loop().run_in_executor(None, self._browser_ws_url)
                async with websockets.connect(ws_url, max_size=None, ping_interval=None) as ws:
                    self._ws = ws
                    self.connected = True
                    await self._send("Target.setDiscoverTargets", {"discover": True})
                    # Pause every new tab until we've switched on network logging for it.
                    await self._send("Target.setAutoAttach",
                                     {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
                    asyncio.ensure_future(self._open_queued())
                    async for raw in ws:
                        msg = json.loads(raw)
                        future = self._calls.get(msg.get("id"))
                        if future is not None:
                            if not future.done():
                                future.set_result(msg)
                            continue
                        await self._handle(msg)
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError, ValueError):
                pass
            except Exception:
                log.exception("browser monitor for lane %s", self.lane.name)
            self.connected = False
            self._ws = None
            self.tabs.clear()
            await asyncio.sleep(1.0)

    def _browser_ws_url(self) -> str:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=1) as r:
            return json.loads(r.read())["webSocketDebuggerUrl"]

    async def _send(self, method: str, params: dict | None = None, session: str | None = None) -> None:
        msg = {"id": next(self._ids), "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self._ws.send(json.dumps(msg))

    async def _handle(self, msg: dict) -> None:
        method = msg.get("method")
        params = msg.get("params", {})
        session = msg.get("sessionId")

        if method in ("Target.targetCreated", "Target.targetInfoChanged"):
            info = params["targetInfo"]
            if info.get("type") != "page":
                return
            self.tabs[info["targetId"]] = {"type": "page", "url": info.get("url", ""), "title": info.get("title", "")}
        elif method == "Target.targetDestroyed":
            self.tabs.pop(params["targetId"], None)
        elif method == "Target.attachedToTarget":
            # Pages, plus their cross-site iframes (ad creatives) and workers.
            child = params["sessionId"]
            await self._send("Network.enable", {}, child)
            await self._send("Target.setAutoAttach",
                             {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, child)
            if params.get("waitingForDebugger"):
                await self._send("Runtime.runIfWaitingForDebugger", {}, child)
        elif method == "Network.requestWillBeSent":
            req = params["request"]
            url = req.get("url", "")
            if not url.startswith(("http://", "https://")):
                return
            self._pending[(session, params["requestId"])] = {
                "t": time.time(), "url": url, "host": urlsplit(url).hostname or "",
                "type": params.get("type", ""), "method": req.get("method", "GET"),
            }
        elif method == "Network.responseReceived":
            entry = self._pending.get((session, params["requestId"]))
            if entry:
                entry["status"] = params["response"].get("status")
        elif method == "Network.loadingFinished":
            entry = self._pending.pop((session, params["requestId"]), None)
            if entry:
                code = entry.get("status")
                entry["outcome"] = f"OK {code}" if code and code < 400 else f"HTTP {code}"
                entry["kind"] = "ok" if code and code < 400 else "other"
                self._finish(entry)
        elif method == "Network.loadingFailed":
            entry = self._pending.pop((session, params["requestId"]), None)
            if entry:
                entry["error"] = params.get("errorText")
                entry["outcome"] = outcome_for(params.get("errorText"), params.get("blockedReason"))
                if entry["error"] == "net::ERR_TUNNEL_CONNECTION_FAILED":
                    # The proxy refuses blocked hosts and also hosts it couldn't reach.
                    verdict = self.lane.stats.last_verdict.get(entry["host"])
                    entry["outcome"] = "blocked by Crumbs" if verdict == "blocked" else "proxy could not connect"
                entry["kind"] = ("crumbs" if entry["outcome"] == "blocked by Crumbs" else
                                 "browser" if entry["outcome"] == "blocked by the browser itself" else "other")
                self._finish(entry)

    def _finish(self, entry: dict) -> None:
        self.counts[entry["kind"]] += 1
        self.requests.append(entry)
