"""Lanes, blocking decisions and stats.

A lane is one independently switchable path to the internet: lane A and B are
HTTP proxies for the two side-by-side browser windows, and the "system" lane is
the DNS server that Windows can be pointed at.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Callable

from .blocklist import Blocklists
from .companies import company_for
from .upstream import Lookup, Upstream, is_ip


@dataclass
class Decision:
    host: str
    blocked: bool
    category: str
    rule: str | None
    company: str | None
    source: str = "local list"  # or "Crumbs resolver"


@dataclass
class LaneStats:
    requests: int = 0
    blocked: int = 0
    bytes_down: int = 0
    bytes_up: int = 0
    categories: Counter = field(default_factory=Counter)
    blocked_companies: Counter = field(default_factory=Counter)
    blocked_domains: Counter = field(default_factory=Counter)
    tracker_domains_seen: set = field(default_factory=set)
    ad_domains_seen: Counter = field(default_factory=Counter)
    recent: deque = field(default_factory=lambda: deque(maxlen=150))
    last_verdict: dict = field(default_factory=dict)
    lookup_ms: deque = field(default_factory=lambda: deque(maxlen=500))  # uncached lookups only

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "blocked": self.blocked,
            "allowed": self.requests - self.blocked,
            "bytes_down": self.bytes_down,
            "bytes_up": self.bytes_up,
            "categories": dict(self.categories),
            "tracker_domains_seen": len(self.tracker_domains_seen),
            "blocked_companies": self.blocked_companies.most_common(10),
            "blocked_domains": self.blocked_domains.most_common(15),
            "ad_domains_seen": self.ad_domains_seen.most_common(10),
            "recent": list(self.recent)[::-1][:60],
            "lookups": _timing(self.lookup_ms),
        }


def _timing(samples) -> dict:
    if not samples:
        return {"count": 0}
    ordered = sorted(samples)
    pick = lambda q: round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)
    return {"count": len(ordered), "median_ms": pick(0.5), "p95_ms": pick(0.95)}


class Lane:
    def __init__(self, name: str, label: str, kind: str, port: int, enabled: bool):
        self.name = name
        self.label = label
        self.kind = kind  # "proxy" or "dns"
        self.port = port
        self.enabled = enabled
        self.running = False
        self.error: str | None = None
        self.stats = LaneStats()
        self.on_toggle: list[Callable[[Lane], None]] = []
        self.monitor = None  # BrowserMonitor for proxy lanes, once windows are launched
        self.note: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "port": self.port,
            "enabled": self.enabled,
            "running": self.running,
            "error": self.error,
            "note": self.note,
            "stats": self.stats.to_dict(),
            "browser": self.monitor.to_dict() if self.monitor else None,
        }


class Engine:
    """Decides what each lane blocks.

    With no Crumbs resolver configured, an enabled lane blocks from the local
    lists (EasyPrivacy, like Crumbs). With ``crumbs`` set, an enabled lane asks
    Crumbs' own resolver and blocks whatever it sinkholes; the local lists are
    then only used to label what was blocked.
    """

    def __init__(self, lists: Blocklists, upstream: Upstream | None = None,
                 crumbs: Upstream | None = None, block_ads: bool = False,
                 signal=None, auction_hosts: list[str] | None = None):
        self.lists = lists
        self.signal = signal  # crumbs_demo.signal.Signal, for the DNS-steered interest group
        # The proposed policy: block identity, not auctions. When on, a Crumbs-on lane
        # still lets these auction hosts through; ID syncs and trackers stay blocked.
        self.auction_hosts = [h.lower().lstrip(".") for h in (auction_hosts or [])]
        self.policy_fix = False
        self.inject_module = True
        self.upstream = upstream
        self.crumbs = crumbs
        self.block_ads = block_ads
        self.lanes: dict[str, Lane] = {}
        self.page_events: deque = deque(maxlen=100)
        self.crumbs_warning: str | None = None

    def add_lane(self, lane: Lane) -> Lane:
        self.lanes[lane.name] = lane
        return lane

    def set_enabled(self, name: str, enabled: bool) -> Lane:
        lane = self.lanes[name]
        if lane.enabled != enabled:
            lane.enabled = enabled
            for callback in lane.on_toggle:
                callback(lane)
        return lane

    def classify(self, host: str):
        return self.lists.classify(host)

    def decide(self, lane: Lane, host: str, record: bool = True) -> Decision:
        """Local-list decision."""
        c = self.lists.classify(host)
        blockable = c.category == "tracker" or (c.category == "ad" and self.block_ads)
        blocked = lane.enabled and blockable
        company = company_for(c.rule) if c.rule else None
        decision = Decision(host, blocked, c.category, c.rule, company)
        if record:
            self.record(lane, decision)
        return decision

    def labelled(self, host: str, blocked: bool, source: str) -> Decision:
        c = self.lists.classify(host)
        company = company_for(c.rule or host) if (c.rule or blocked) else None
        return Decision(host, blocked, c.category, c.rule, company, source)

    def is_auction_host(self, host: str) -> bool:
        h = host.lower()
        return any(h == a or h.endswith("." + a) for a in self.auction_hosts)

    def uses_crumbs(self, lane: Lane) -> bool:
        return lane.enabled and self.crumbs is not None

    async def resolve(self, lane: Lane, host: str) -> tuple[Decision, Lookup | None]:
        """Decide and resolve a hostname for a proxy lane. Lookup is None when blocked."""
        if is_ip(host):
            return Decision(host, False, "other", None, None), Lookup([host.strip("[]")], [], False)
        if self.signal and host.lower() == self.signal.host:
            # Only the Crumbs resolver knows this name. Its answer is the group's address.
            if not lane.enabled:
                decision = Decision(host, False, "signal", None, None, "normal DNS")
                self.record(lane, decision, note="no answer: only Crumbs knows this name")
                return decision, Lookup([], [], False)
            g = self.signal.by_key(self.signal.group)
            decision = Decision(host, False, "signal", None, "Crumbs", "Crumbs resolver")
            self.record(lane, decision, note=f"Crumbs signal: {g['label'] if g else 'no group (opted out)'}"
                                             f" -> {self.signal.address()}")
            return decision, Lookup([self.signal.address()], [], False)
        if lane.enabled and self.policy_fix and self.is_auction_host(host):
            decision = self.labelled(host, False, "proposed policy")
            started = time.perf_counter()
            result = await self.upstream.lookup(host)
            if not result.cached:
                lane.stats.lookup_ms.append((time.perf_counter() - started) * 1000)
            self.record(lane, decision, note="auction allowed by the proposed policy")
            return decision, result
        if self.uses_crumbs(lane):
            started = time.perf_counter()
            result = await self.crumbs.lookup(host)
            if not result.cached:
                lane.stats.lookup_ms.append((time.perf_counter() - started) * 1000)
            decision = self.labelled(host, result.sinkholed, "Crumbs resolver")
            self.record(lane, decision)
            return decision, None if decision.blocked else result
        decision = self.decide(lane, host, record=False)
        if decision.blocked:
            self.record(lane, decision)
            return decision, None
        started = time.perf_counter()
        result = await self.upstream.lookup(host)
        if not result.cached:
            lane.stats.lookup_ms.append((time.perf_counter() - started) * 1000)
        if lane.enabled:
            for cname in result.cnames:
                cloaked = self.decide(lane, cname, record=False)
                if cloaked.blocked:
                    cloaked.host = host
                    self.record(lane, cloaked, note=f"CNAME cloak to {cname}")
                    return cloaked, None
        self.record(lane, decision)
        return decision, result

    def record(self, lane: Lane, d: Decision, note: str | None = None) -> None:
        s = lane.stats
        s.requests += 1
        s.categories[d.category] += 1
        if d.category == "tracker":
            s.tracker_domains_seen.add(d.rule)
        if d.category == "ad" and not d.blocked:
            s.ad_domains_seen[d.rule] += 1
        if d.blocked:
            s.blocked += 1
            s.blocked_companies[d.company] += 1
            s.blocked_domains[d.host] += 1
        s.last_verdict[d.host] = "blocked" if d.blocked else "allowed"
        s.recent.append({
            "t": time.time(),
            "host": d.host,
            "verdict": "blocked" if d.blocked else "allowed",
            "category": d.category,
            "company": d.company,
            "source": d.source,
            "note": note,
        })

    def reset_stats(self) -> None:
        for lane in self.lanes.values():
            lane.stats = LaneStats()
            if lane.monitor:
                lane.monitor.reset()
        self.page_events.clear()

    def state(self) -> dict:
        return {
            "lanes": [lane.to_dict() for lane in self.lanes.values()],
            "lists": {
                "trackers": len(self.lists.trackers),
                "ads": len(self.lists.ads),
                "sources": self.lists.sources,
            },
            "block_ads": self.block_ads,
            "mode": "crumbs" if self.crumbs else "local",
            "crumbs_resolver": self.crumbs.describe() if self.crumbs else None,
            "crumbs_warning": self.crumbs_warning,
            "upstream": self.upstream.describe() if self.upstream else None,
            "policy_fix": self.policy_fix,
            "auction_hosts": self.auction_hosts,
            "inject_module": self.inject_module,
            "signal": self.signal.to_dict() if self.signal else None,
            "page_events": list(self.page_events)[::-1],
        }
