"""Company and bidder logos for the control panel.

Logos are the sites' own favicons, fetched once from a public favicon service
and cached in .cache/logos, so the demo works offline after its first run.
Anything that can't be fetched gets a coloured letter badge instead.
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.request

from .blocklist import CACHE_DIR
from .companies import COMPANIES

LOGO_DIR = CACHE_DIR / "logos"
DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,100}\.[a-z]{2,}$")
SOURCES = [
    "https://icons.duckduckgo.com/ip3/{domain}.ico",
    "https://www.google.com/s2/favicons?domain={domain}&sz=64",
]

# Company name (as shown in the panel) -> the domain whose logo represents it.
COMPANY_LOGOS = {
    "Google": "google.com", "Meta": "meta.com", "Microsoft": "microsoft.com",
    "Microsoft (Xandr)": "microsoft.com", "Microsoft (LinkedIn)": "linkedin.com",
    "Amazon": "amazon.com", "Comscore": "comscore.com", "Quantcast": "quantcast.com",
    "Chartbeat": "chartbeat.com", "Hotjar": "hotjar.com", "Adobe": "adobe.com",
    "The Trade Desk": "thetradedesk.com", "LiveRamp": "liveramp.com", "LiveIntent": "liveintent.com",
    "ID5": "id5.io", "Lotame": "lotame.com", "Oracle": "oracle.com", "Oracle (Moat)": "oracle.com",
    "Salesforce": "salesforce.com", "Neustar": "home.neustar", "Tapad": "tapad.com",
    "Criteo": "criteo.com", "Taboola": "taboola.com", "Outbrain": "outbrain.com",
    "Magnite": "magnite.com", "PubMatic": "pubmatic.com", "OpenX": "openx.com",
    "Index Exchange": "indexexchange.com", "Equativ": "equativ.com", "TripleLift": "triplelift.com",
    "MediaMath": "mediamath.com", "DoubleVerify": "doubleverify.com", "IAS": "integralads.com",
    "TikTok": "tiktok.com", "X": "x.com", "Snap": "snap.com", "Pinterest": "pinterest.com",
    "Permutive": "permutive.com", "Tealium": "tealium.com", "New Relic": "newrelic.com",
    "Twilio Segment": "segment.com", "Mixpanel": "mixpanel.com", "Amplitude": "amplitude.com",
    "Optimizely": "optimizely.com", "Teads": "teads.com", "Media.net": "media.net",
    "Kargo": "kargo.com", "Ozone": "ozoneproject.com", "GumGum": "gumgum.com",
    "Wunderkind": "wunderkind.co", "VWO": "vwo.com", "Akamai": "akamai.com",
    "StackAdapt": "stackadapt.com", "Sovrn": "sovrn.com", "Sharethrough": "sharethrough.com",
    "Crumbs": "crumbs.com", "eyeo": "eyeo.com",
}

# Prebid bidder code -> logo domain.
BIDDER_LOGOS = {
    "appnexus": "microsoft.com", "msft": "microsoft.com", "appnexusAst": "microsoft.com",
    "criteo": "criteo.com", "ix": "indexexchange.com", "rubicon": "magnite.com",
    "ttd": "thetradedesk.com", "ozone": "ozoneproject.com", "pubmatic": "pubmatic.com",
    "triplelift": "triplelift.com", "kargo": "kargo.com", "gumgum": "gumgum.com",
    "teads": "teads.com", "openx": "openx.com", "oxd": "openx.com", "amazon": "amazon.com",
    "sharethrough": "sharethrough.com", "smartadserver": "equativ.com", "equativ": "equativ.com",
    "adform": "adform.com", "sovrn": "sovrn.com", "medianet": "media.net", "yieldmo": "yieldmo.com",
    "33across": "33across.com", "seedtag": "seedtag.com", "nextMillennium": "nextmillennium.io",
    "improvedigital": "improvedigital.com", "richaudience": "richaudience.com",
    "outbrain": "outbrain.com", "taboola": "taboola.com", "minutemedia": "minutemedia.com",
}


def logo_map() -> dict:
    """What the panel needs to pick a logo for a company name or bidder code."""
    companies = dict(COMPANY_LOGOS)
    for domain, name in COMPANIES.items():
        companies.setdefault(name, domain)
    return {"companies": companies, "bidders": BIDDER_LOGOS, "domains": COMPANIES}


def _letter_badge(domain: str) -> bytes:
    letter = (domain[:1] or "?").upper()
    hue = int(hashlib.md5(domain.encode()).hexdigest()[:2], 16) * 360 // 256
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<rect width="32" height="32" rx="7" fill="hsl({hue},45%,46%)"/>'
        '<text x="16" y="21.5" font-family="Segoe UI,Arial,sans-serif" font-size="17" '
        f'font-weight="700" fill="#fff" text-anchor="middle">{letter}</text></svg>'
    ).encode()


def _sniff(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if b"<svg" in data[:300]:
        return "image/svg+xml"
    return None


def get_logo(domain: str, timeout: float = 4.0) -> tuple[str, bytes]:
    """(content type, bytes). Blocking: call from a thread."""
    domain = domain.lower().strip(".")
    if not DOMAIN_RE.match(domain):
        return "image/svg+xml", _letter_badge(domain or "?")
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    cached = LOGO_DIR / f"{domain}.img"
    missing = LOGO_DIR / f"{domain}.missing"
    if cached.exists():
        data = cached.read_bytes()
        return _sniff(data) or "image/x-icon", data
    # After a failed fetch (e.g. offline), wait 10 minutes before trying again.
    if not missing.exists() or time.time() - missing.stat().st_mtime > 600:
        for source in SOURCES:
            try:
                req = urllib.request.Request(source.format(domain=domain),
                                             headers={"User-Agent": "Mozilla/5.0 crumbs-demo"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = resp.read(200_000)
                kind = _sniff(data)
                if kind and len(data) > 100:
                    cached.write_bytes(data)
                    return kind, data
            except OSError:
                continue
        missing.touch()
    return "image/svg+xml", _letter_badge(domain)
