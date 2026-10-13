"""Domain block lists.

DNS only sees hostnames, so from Adblock Plus style lists (EasyPrivacy,
EasyList) we keep only whole-domain rules (``||example.com^``). Options that
just narrow the request type or mark it third-party are dropped, because DNS
can't tell them apart, so the domain is blocked outright. Rules limited to
certain sites (``$domain=``), popups, paths or cosmetic hiding can't be
expressed in DNS and are skipped: that is the gap between a DNS blocker like
Crumbs and an in-browser blocker like Adblock Plus.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SEED_DIR = PACKAGE_DIR / "data"
CACHE_DIR = PACKAGE_DIR.parent / ".cache"
LIST_DIR = CACHE_DIR / "lists"

LIST_SOURCES = {
    "trackers": ["https://easylist.to/easylist/easyprivacy.txt",
                 "https://raw.githubusercontent.com/easylist/easylist/gh-pages/easyprivacy.txt"],
    "ads": ["https://easylist.to/easylist/easylist.txt",
            "https://raw.githubusercontent.com/easylist/easylist/gh-pages/easylist.txt"],
}

# Options a DNS blocker can ignore (it blocks the whole domain anyway).
DNS_SAFE_OPTIONS = {
    "third-party", "3p", "script", "image", "xmlhttprequest", "xhr", "ping", "subdocument",
    "stylesheet", "css", "media", "font", "websocket", "other", "object", "important", "all",
}

_DOMAIN = r"([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.[a-z][a-z0-9\-]+)"
_ABP_RULE = re.compile(rf"^\|\|{_DOMAIN}\^(?:\$(.*))?$")
_HOSTS_LINE = re.compile(rf"^(?:0\.0\.0\.0|127\.0\.0\.1|::1?)\s+{_DOMAIN}$")
_PLAIN = re.compile(rf"^{_DOMAIN}$")


def parse_rules(text: str) -> tuple[set[str], set[str]]:
    """Return (blocked domains, exception domains) from ABP, hosts or plain lists."""
    blocked: set[str] = set()
    exceptions: set[str] = set()
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip().lower()
        if not line or line[0] in "!#[":
            continue
        is_exception = line.startswith("@@")
        if is_exception:
            line = line[2:]
        m = _ABP_RULE.match(line)
        if m:
            options = set(filter(None, (m.group(2) or "").split(",")))
            if options - DNS_SAFE_OPTIONS:
                continue
            (exceptions if is_exception else blocked).add(m.group(1))
            continue
        if is_exception:
            continue
        m = _HOSTS_LINE.match(line) or _PLAIN.match(line)
        if m and m.group(1) not in ("localhost", "localhost.localdomain"):
            blocked.add(m.group(1))
    return blocked, exceptions


class DomainSet:
    """Suffix-matching set: a rule for example.com also matches a.b.example.com."""

    def __init__(self, domains=(), exceptions=()):
        self.domains = set(domains)
        self.exceptions = set(exceptions)

    def __len__(self) -> int:
        return len(self.domains)

    def match(self, host: str) -> str | None:
        labels = host.lower().rstrip(".").split(".")
        suffixes = [".".join(labels[i:]) for i in range(len(labels) - 1)]
        if any(s in self.exceptions for s in suffixes):
            return None
        for s in suffixes:
            if s in self.domains:
                return s
        return None

    @classmethod
    def from_text(cls, text: str) -> "DomainSet":
        return cls(*parse_rules(text))


@dataclass
class Classification:
    category: str  # "tracker", "ad" or "other"
    rule: str | None


class Blocklists:
    def __init__(self, trackers: DomainSet, ads: DomainSet, sources: dict[str, str]):
        self.trackers = trackers
        self.ads = ads
        self.sources = sources

    def classify(self, host: str) -> Classification:
        rule = self.trackers.match(host)
        if rule:
            return Classification("tracker", rule)
        rule = self.ads.match(host)
        if rule:
            return Classification("ad", rule)
        return Classification("other", None)

    @classmethod
    def load(cls) -> "Blocklists":
        """Prefer downloaded lists in .cache/lists, fall back to the bundled seeds."""
        sets, sources = {}, {}
        for name in LIST_SOURCES:
            cached = LIST_DIR / f"{name}.txt"
            path = cached if cached.exists() else SEED_DIR / f"seed_{name}.txt"
            sets[name] = DomainSet.from_text(path.read_text(encoding="utf-8"))
            sources[name] = "downloaded" if path == cached else "bundled 2026-10-13 snapshot"
        return cls(sets["trackers"], sets["ads"], sources)


def fetch_list(name: str, timeout: float = 30.0) -> str:
    errors = []
    for url in LIST_SOURCES[name]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "crumbs-demo/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            if len(parse_rules(text)[0]) >= 100:
                return text
            errors.append(f"{url}: too few domain rules")
        except OSError as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("; ".join(errors))


def domains_only(text: str, source: str) -> str:
    """Compact form: just the DNS-enforceable rules, still in ABP syntax."""
    blocked, exceptions = parse_rules(text)
    lines = [f"! Domain-level rules extracted from {source}", f"! {len(blocked)} rules"]
    lines += [f"@@||{d}^" for d in sorted(exceptions)]
    lines += [f"||{d}^" for d in sorted(blocked)]
    return "\n".join(lines) + "\n"


def download_lists(timeout: float = 30.0) -> dict[str, int]:
    LIST_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name in LIST_SOURCES:
        text = fetch_list(name, timeout)
        compact = domains_only(text, LIST_SOURCES[name][0])
        (LIST_DIR / f"{name}.txt").write_text(compact, encoding="utf-8")
        counts[name] = len(parse_rules(compact)[0])
    return counts
