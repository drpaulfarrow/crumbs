"""Read Prebid.js auction results out of a live page and summarise them.

What this sees: the header-bidding part of a page's monetization (bids each
Prebid bidder returned, winners, no-bids, timeouts, errors). What it doesn't:
Google AdX, direct deals and Amazon TAM, which decide outside Prebid. CPMs are
bids in the header auction, not the final clearing price in the ad server.
"""

from __future__ import annotations

from collections import defaultdict

# Runs in the page. Finds every Prebid global (sites rename `pbjs`) and returns
# plain data only.
PREBID_SNAPSHOT_JS = r"""
(() => {
  const names = new Set([...(window._pbjsGlobals || []), "pbjs"]);
  const out = [];
  const bidOf = (b) => ({ id: b.adId || b.requestId || "", auction: b.auctionId || "", unit: b.adUnitCode,
    bidder: b.bidderCode || b.bidder,
    cpm: Number(b.cpm) || 0, currency: b.currency || "", size: b.size || `${b.width}x${b.height}`,
    ms: b.timeToRespond });
  for (const name of names) {
    const p = window[name];
    if (!p || typeof p.getEvents !== "function") continue;
    // The event log covers every auction on the page. getBidResponses() only
    // returns the latest auction's bids for slots still registered, which on
    // real sites (lazy loading, refresh, removeAdUnit) is often empty.
    let events = [];
    try { events = p.getEvents() || []; } catch (e) {}
    const bids = [], won = [], slots = new Set();
    const requested = new Set(), noBid = new Set(), timedOut = new Set(), errored = new Set();
    let auctions = 0, lastUser = null;
    for (const e of events) {
      const a = e.args || {};
      switch (e.eventType) {
        case "auctionInit": auctions++; break;
        case "bidRequested": {
          requested.add(a.bidderCode);
          // What bidders were told about the user, from the latest request.
          const u = (a.ortb2 && a.ortb2.user) || {};
          const firstBid = (a.bids || [])[0] || {};
          const eids = (u.ext && u.ext.eids) || firstBid.userIdAsEids || [];
          lastUser = {
            bidder: a.bidderCode,
            data: (u.data || []).map(d => ({ name: d.name || "", segtax: d.ext && d.ext.segtax,
              ids: (d.segment || []).map(x => x.id) })),
            keywords: u.keywords || "",
            eids: eids.map(e => e.source).filter(Boolean),
          };
          (a.bids || []).forEach(b => slots.add(b.adUnitCode));
          break;
        }
        case "bidResponse": bids.push(bidOf(a)); break;
        case "bidWon": won.push(bidOf(a)); break;
        case "noBid": noBid.add(a.bidder || a.bidderCode); break;
        case "bidTimeout": (Array.isArray(a) ? a : [a]).forEach(t => timedOut.add(t.bidder || t.bidderCode)); break;
        case "bidderError": errored.add((a.bidderRequest || {}).bidderCode || a.bidderCode); break;
      }
    }
    if (!events.length && typeof p.getBidResponses === "function") {
      // Fallback for builds that keep no event history.
      for (const [unit, v] of Object.entries(p.getBidResponses() || {})) {
        slots.add(unit);
        for (const b of (v.bids || [])) bids.push(bidOf(b));
      }
    }
    out.push({ global: name, version: p.version || "", ad_units: slots.size, auctions, bids, won,
      requested: [...requested].filter(Boolean), no_bid: [...noBid].filter(Boolean),
      timed_out: [...timedOut].filter(Boolean), errored: [...errored].filter(Boolean), user: lastUser,
      crumbs: window.__crumbs ? { status: window.__crumbs.status, group: window.__crumbs.group,
        mode: window.__crumbs.crumbsMode, tagged: window.__crumbs.auctionsTagged, gam: window.__crumbs.gam } : null });
  }
  return out;
})()
"""


def summarise(snapshots: list[dict]) -> dict:
    """Combine every Prebid instance on a page into one summary."""
    if not snapshots:
        return {"found": False}
    # A winning bid was also a received bid. Some sites' event logs drop
    # bidResponse entries but keep bidWon, so merge the two (deduplicated by ad id).
    bids, seen = [], set()
    for s in snapshots:
        for b in s.get("bids", []) + s.get("won", []):
            key = b.get("id") or (b.get("auction"), b.get("unit"), b.get("bidder"), b.get("cpm"))
            if key not in seen:
                seen.add(key)
                bids.append(b)
    won = [b for s in snapshots for b in s.get("won", [])]
    requested = sorted({x for s in snapshots for x in s.get("requested", [])})
    bidders_bid = sorted({b["bidder"] for b in bids if b.get("bidder")})
    # Best bid per slot per auction: a slot refreshed three times is three chances to earn.
    top_per_unit: dict[tuple[str, str], float] = {}
    by_bidder: dict[str, dict] = defaultdict(lambda: {"bids": 0, "max_cpm": 0.0, "sum_cpm": 0.0})
    for b in bids:
        key = (b.get("auction", ""), b["unit"])
        top_per_unit[key] = max(top_per_unit.get(key, 0.0), b["cpm"])
        entry = by_bidder[b["bidder"]]
        entry["bids"] += 1
        entry["sum_cpm"] += b["cpm"]
        entry["max_cpm"] = max(entry["max_cpm"], b["cpm"])
    units_with_bids = {unit for _, unit in top_per_unit}
    currencies = sorted({b["currency"] for b in bids if b.get("currency")})
    return {
        "found": True,
        "versions": sorted({s.get("version", "") for s in snapshots}),
        "ad_units": max(sum(s.get("ad_units", 0) for s in snapshots), len(units_with_bids)),
        "auctions": sum(s.get("auctions", 0) for s in snapshots),
        "bidders_requested": sorted(set(requested) | set(bidders_bid)),
        "bidders_bid": bidders_bid,
        "timed_out": sorted({x for s in snapshots for x in s.get("timed_out", [])}),
        "errored": sorted({x for s in snapshots for x in s.get("errored", [])}),
        "bids": len(bids),
        "avg_cpm": round(sum(b["cpm"] for b in bids) / len(bids), 3) if bids else 0.0,
        "top_bid_sum": round(sum(top_per_unit.values()), 3),
        "units_with_bids": len(units_with_bids),
        "won": len(won),
        "won_sum": round(sum(b["cpm"] for b in won), 3),
        "currency": "/".join(currencies) or "",
        "user": next((s["user"] for s in snapshots if s.get("user")), None),
        "crumbs": next((s["crumbs"] for s in snapshots if s.get("crumbs")), None),
        "by_bidder": {k: {**v, "sum_cpm": round(v["sum_cpm"], 3), "max_cpm": round(v["max_cpm"], 3)}
                      for k, v in sorted(by_bidder.items())},
    }
