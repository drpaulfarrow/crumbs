"""Paired A/B measurement at scale: how Crumbs changes monetization per site and per ad-tech company.

For each round, two browsers start as identical copies of the warm-up profile:
one with Crumbs off, one with Crumbs on. Both load the same page at the same
moment, accept the cookie banner the same way, scroll the same way (so
lazy-loaded slots run their auctions), then the page's Prebid results, Google
ad slot fill and every request's outcome are written to visits.jsonl. Pairing
cancels out time of day, campaign pacing and site changes.

Keep volumes modest: ads rendered by automated browsers are invalid traffic
that advertisers pay for. This never clicks ads.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from urllib.parse import urlsplit

from .blocklist import PACKAGE_DIR, Blocklists
from .browser_monitor import LaneMonitor
from .engine import Engine, Lane
from .launcher import launch_ab, warm_profile_state
from .prebid_reader import PREBID_SNAPSHOT_JS, summarise
from .proxy import LaneProxy
from .upstream import Upstream

DEFAULT_SITES = PACKAGE_DIR / "data" / "sites_uk.txt"

# Clicks "accept" on a cookie banner, only inside consent-manager frames or containers.
CONSENT_JS = r"""
(() => {
  const word = /^(accept( all)?( cookies)?|agree( (and|&) (close|continue))?|i agree|allow all( cookies)?|consent|yes,? i[’']?m happy|ok(ay)?|got it|accept (&|and) continue)$/i;
  const cmpFrame = /consent|cmp|privacy|sourcepoint|sp_message|didomi|onetrust|quantcast|usercentrics|trustarc|cookiebot|fundingchoices/i
    .test(location.hostname + location.pathname);
  const cmpRoot = '[id*="onetrust"],[id*="didomi"],[class*="qc-cmp"],[id*="sp_message"],[class*="cmp"],[id*="cmp"],' +
    '[class*="consent"],[id*="consent"],[class*="cookie"],[id*="cookie"],[id*="CybotCookiebot"],[class*="fc-consent"],[class*="truste"]';
  for (const sel of ["#onetrust-accept-btn-handler", "#didomi-notice-agree-button",
                     "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll", ".fc-cta-consent"]) {
    const el = document.querySelector(sel);
    if (el) { el.click(); return sel; }
  }
  const buttons = document.querySelectorAll('button,[role=button],a,input[type=button],input[type=submit]');
  for (const b of buttons) {
    const t = (b.innerText || b.value || b.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ");
    if (!t || t.length > 40 || !word.test(t)) continue;
    if (!cmpFrame && !b.closest(cmpRoot)) continue;
    b.click();
    return t;
  }
  return null;
})()
"""

# Google Ad Manager slots: how many were requested, answered, and filled.
GPT_SNAPSHOT_JS = r"""
(() => {
  const g = window.googletag;
  if (!g || typeof g.pubads !== "function" || !g.apiReady) return { found: false };
  const slots = g.pubads().getSlots();
  let responded = 0, filled = 0, prebidTargeted = 0;
  for (const s of slots) {
    const info = s.getResponseInformation ? s.getResponseInformation() : null;
    if (info) { responded++; if (info.creativeId || info.lineItemId || info.advertiserId) filled++; }
    const pb = s.getTargeting ? s.getTargeting("hb_pb") : [];
    if (pb && pb.length && pb[0]) prebidTargeted++;
  }
  return { found: true, slots: slots.length, responded, filled, prebid_targeted: prebidTargeted };
})()
"""

SCROLL_JS = "window.scrollBy(0, Math.round(window.innerHeight * 0.8)); true"


def load_sites(path: Path) -> list[str]:
    sites = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            sites.append(line if "://" in line else f"https://{line}")
    return sites


async def visit(monitor: LaneMonitor, url: str, args) -> dict:
    session = monitor.page_session()
    started = time.time()
    await monitor.call("Page.navigate", {"url": url}, session=session, timeout=30)
    await asyncio.sleep(args.settle)

    clicked = []
    for _ in range(3):
        results = await monitor.evaluate_everywhere(CONSENT_JS)
        clicked = [r for r in results if isinstance(r, str)]
        if clicked:
            await asyncio.sleep(3)  # let the page react to consent and start its auctions
            break
        await asyncio.sleep(2)

    deadline = time.monotonic() + args.scroll
    while time.monotonic() < deadline:
        await monitor.evaluate(SCROLL_JS, session, timeout=5)
        await asyncio.sleep(1.5)
    await asyncio.sleep(args.dwell)

    raw = await monitor.evaluate(PREBID_SNAPSHOT_JS, session) or []
    gpt = await monitor.evaluate(GPT_SNAPSHOT_JS, session) or {"found": False}
    final_url = await monitor.evaluate("location.href", session) or ""
    return {
        "consent_clicked": clicked[:3],
        "prebid": summarise(raw),
        "gpt": gpt,
        "requests": dict(monitor.counts),
        "by_company": [[c, k, n] for (c, k), n in monitor.tally.most_common()],
        "sync": dict(monitor.sync_tally),
        "final_url": final_url,
        "seconds": round(time.time() - started, 1),
    }


async def run(args, crumbs_spec: str | None, browser: str) -> Path:
    lists = Blocklists.load()
    crumbs = Upstream(crumbs_spec, os_fallback=False) if crumbs_spec else None
    engine = Engine(lists, upstream=Upstream(args.upstream), crumbs=crumbs)
    lanes = {
        "off": engine.add_lane(Lane("off", "Crumbs off", "proxy", args.port_off, enabled=False)),
        "on": engine.add_lane(Lane("on", "Crumbs on", "proxy", args.port_on, enabled=True)),
    }
    for lane in lanes.values():
        proxy = LaneProxy(engine, lane)
        await proxy.start()
        if not lane.running:
            raise SystemExit(f"Could not start proxy for lane {lane.name}: {lane.error}")

    sites = load_sites(Path(args.sites))
    total = args.rounds * len(sites)
    if total > args.max_visits:
        raise SystemExit(f"{total} paired visits exceeds --max-visits {args.max_visits}. "
                         "Lower --rounds or the site list (or raise the cap deliberately).")
    warm = not args.no_warm and warm_profile_state()["exists"]
    out = Path(args.out or f"results/{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps({
        "started": time.time(), "sites": sites, "rounds": args.rounds, "warm_profile": warm,
        "crumbs": crumbs.describe() if crumbs else "local EasyPrivacy list",
        "settle": args.settle, "scroll": args.scroll, "dwell": args.dwell, "browser": browser,
    }, indent=2), encoding="utf-8")
    print(f"\n  {len(sites)} sites x {args.rounds} rounds = {total} paired visits "
          f"(~{total * (args.settle + args.scroll + args.dwell + 10) / 3600:.1f} h). "
          f"Warm profile: {'yes' if warm else 'no (fresh profiles)'}.")
    print(f"  Crumbs on = {crumbs.describe() if crumbs else 'local EasyPrivacy list'}. Writing to {out}\n")

    rng = random.Random(args.seed)
    cdp = {"off": args.cdp_off, "on": args.cdp_on}
    with open(out / "visits.jsonl", "a", encoding="utf-8") as log:
        for rnd in range(args.rounds):
            order = sites[:]
            rng.shuffle(order)
            extra = ["--headless=new"] if args.headless else []
            launch_ab({n: (lanes[n].port, cdp[n]) for n in lanes}, [], prefer=browser, warm=warm,
                      extra=extra, tag="measure")
            monitors = {n: LaneMonitor(lanes[n], cdp[n]) for n in lanes}
            for m in monitors.values():
                m.start(poll_prebid=False)
            if not all(await asyncio.gather(*(m.wait_ready() for m in monitors.values()))):
                print("  Browsers did not come up; skipping this round.")
                for m in monitors.values():
                    m.stop()
                continue
            for i, url in enumerate(order, 1):
                for m in monitors.values():
                    m.reset()
                try:
                    results = await asyncio.gather(*(visit(monitors[n], url, args) for n in lanes))
                except Exception as e:  # one bad site shouldn't end the run
                    print(f"  round {rnd + 1} {url}: failed ({e})")
                    continue
                for name, res in zip(lanes, results):
                    log.write(json.dumps({"round": rnd, "site": url, "host": urlsplit(url).hostname,
                                          "lane": name, "crumbs": lanes[name].enabled, "t": time.time(),
                                          **res}) + "\n")
                log.flush()
                a, b = (r["prebid"] for r in results)
                fmt = lambda s: f"{s.get('top_bid_sum', 0):.2f} ({s.get('bids', 0)} bids)" if s.get("found") else "no Prebid"
                print(f"  round {rnd + 1}/{args.rounds}  {i:>3}/{len(order)}  {urlsplit(url).hostname:<32} "
                      f"off {fmt(a):<22} on {fmt(b)}")
                await asyncio.sleep(args.pause)
            for m in monitors.values():
                await m.call("Browser.close", timeout=5)
                m.stop()
            await asyncio.sleep(2)
    return out
