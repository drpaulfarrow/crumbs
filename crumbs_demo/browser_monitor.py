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
import re
from collections import Counter, deque
from urllib.parse import urlsplit

import websockets

from .companies import company_for
from .prebid_reader import PREBID_SNAPSHOT_JS, summarise

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


# Rough match for ID-sync / cookie-match requests (user syncs, pixels that swap IDs).
SYNC_URL = re.compile(r"(usersync|user_sync|/usync|cookiesync|cookie_sync|/sync[/?.]|/match[/?]|"
                      r"setuid|getuid|/cm[/?]|/pixel/sync|idsync|/ups/|ixmatch|syncframe|async_usersync)", re.I)


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
        self._page_sessions: dict[str, str] = {}  # top-level tab targetId -> sessionId
        self._sessions: dict[str, dict] = {}  # every attached session -> {type, url}
        self.tally: Counter = Counter()  # (company, outcome kind) -> requests, since last reset
        self.sync_tally: Counter = Counter()  # outcome kind -> ID-sync requests, since last reset
        self.prebid: dict[str, dict] = {}  # targetId -> {url, title, summary}
        # Returns the Crumbs Prebid module source to inject into new pages, or None.
        self.inject_source = None

    def start(self, poll_prebid: bool = True) -> None:
        self._task = asyncio.ensure_future(self._run())
        self._poll_task = asyncio.ensure_future(self._poll_prebid()) if poll_prebid else None

    def stop(self) -> None:
        for task in (self._task, getattr(self, "_poll_task", None)):
            if task:
                task.cancel()

    # --- helpers for scripted runs (measure.py) ---------------------------------

    def page_session(self) -> str | None:
        for target_id, session in self._page_sessions.items():
            url = self.tabs.get(target_id, {}).get("url", "")
            if not url.startswith(("devtools://", "edge://", "chrome://")):
                return session
        return None

    async def wait_ready(self, timeout: float = 45.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected and self.page_session():
                return True
            await asyncio.sleep(0.3)
        return False

    async def call(self, method: str, params: dict | None = None, session: str | None = None,
                   timeout: float = 15.0) -> dict | None:
        return await self._call(method, params, timeout=timeout, session=session)

    async def evaluate(self, expression: str, session: str | None = None, timeout: float = 15.0):
        reply = await self._call("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                      "awaitPromise": True},
                                 timeout=timeout, session=session or self.page_session())
        return ((reply or {}).get("result", {}).get("result", {}) or {}).get("value")

    async def evaluate_everywhere(self, expression: str) -> list:
        """Run in the page and every attached iframe (consent banners often live in iframes)."""
        sessions = [s for s, info in list(self._sessions.items()) if info.get("type") in ("page", "iframe")]
        return await asyncio.gather(*(self.evaluate(expression, s, timeout=5) for s in sessions),
                                    return_exceptions=True)

    async def _poll_prebid(self, every: float = 2.0) -> None:
        """Read each tab's Prebid results every few seconds (lazy-loaded and refreshed slots keep bidding)."""
        while True:
            await asyncio.sleep(every)
            if not self.connected:
                continue
            for target_id, session in list(self._page_sessions.items()):
                reply = await self._call("Runtime.evaluate",
                                         {"expression": PREBID_SNAPSHOT_JS, "returnByValue": True}, session=session)
                value = ((reply or {}).get("result", {}).get("result", {}) or {}).get("value")
                if value is None:
                    continue
                tab = self.tabs.get(target_id, {})
                self.prebid[target_id] = {"url": tab.get("url", ""), "title": tab.get("title", ""),
                                          "summary": summarise(value)}

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

    async def _call(self, method: str, params: dict | None = None, timeout: float = 5.0,
                    session: str | None = None) -> dict | None:
        """Send a command and wait for its reply. Not for use inside _handle."""
        if not self._ws:
            return None
        msg_id = next(self._ids)
        future = asyncio.get_running_loop().create_future()
        self._calls[msg_id] = future
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self._ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._calls.pop(msg_id, None)

    async def close_browser(self) -> bool:
        """Close this lane's browser window. True if one was open."""
        if not self.connected or not self._ws:
            return False
        await self._call("Browser.close", timeout=3)
        return True

    def reset(self) -> None:
        self.tally.clear()
        self.sync_tally.clear()
        self.prebid.clear()
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
            "prebid": [v for k, v in self.prebid.items() if k in self.tabs],
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
            self._page_sessions.clear()
            self._sessions.clear()
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
            self._page_sessions.pop(params["targetId"], None)
            self.prebid.pop(params["targetId"], None)
        elif method == "Target.attachedToTarget":
            # Pages, plus their cross-site iframes (ad creatives) and workers.
            child = params["sessionId"]
            info = params.get("targetInfo", {})
            self._sessions[child] = {"type": info.get("type"), "url": info.get("url", "")}
            if info.get("type") == "page":
                self._page_sessions[info["targetId"]] = child
            await self._send("Network.enable", {}, child)
            source = self.inject_source() if (self.inject_source and info.get("type") == "page") else None
            if source:
                # Runs before the page's own scripts, like a publisher's Prebid module would.
                # Chrome only applies it once the Page domain is enabled for the session.
                await self._send("Page.enable", {}, child)
                await self._send("Page.addScriptToEvaluateOnNewDocument", {"source": source}, child)
            await self._send("Target.setAutoAttach",
                             {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, child)
            if params.get("waitingForDebugger"):
                await self._send("Runtime.runIfWaitingForDebugger", {}, child)
        elif method == "Target.detachedFromTarget":
            self._sessions.pop(params.get("sessionId"), None)
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
        if entry["host"]:
            self.tally[(company_for(entry["host"]), entry["kind"])] += 1
            if SYNC_URL.search(entry["url"]):
                self.sync_tally[entry["kind"]] += 1
