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
  for (const name of names) {
    const p = window[name];
    if (!p || typeof p.getBidResponses !== "function") continue;
    const bids = [];
    for (const [unit, v] of Object.entries(p.getBidResponses() || {})) {
      for (const b of (v.bids || [])) {
        bids.push({ unit, bidder: b.bidderCode || b.bidder, cpm: Number(b.cpm) || 0,
          currency: b.currency || "", size: b.size || `${b.width}x${b.height}`,
          ms: b.timeToRespond, status: b.status || "" });
      }
    }
    const won = (typeof p.getAllWinningBids === "function" ? p.getAllWinningBids() : [])
      .map(b => ({ unit: b.adUnitCode, bidder: b.bidderCode, cpm: Number(b.cpm) || 0, currency: b.currency || "" }));
    const requested = new Set(), noBid = new Set(), timedOut = new Set(), errored = new Set();
    let auctions = 0;
    try {
      for (const e of p.getEvents()) {
        const a = e.args || {};
        if (e.eventType === "auctionInit") auctions++;
        else if (e.eventType === "bidRequested") requested.add(a.bidderCode);
        else if (e.eventType === "noBid") noBid.add(a.bidder || a.bidderCode);
        else if (e.eventType === "bidTimeout") (Array.isArray(a) ? a : [a]).forEach(t => timedOut.add(t.bidder || t.bidderCode));
        else if (e.eventType === "bidderError") errored.add((a.bidderRequest || {}).bidderCode || a.bidderCode);
      }
    } catch (e) {}
    const units = (p.adUnits || []).length;
    out.push({ global: name, version: p.version || "", ad_units: units, auctions, bids, won,
      requested: [...requested].filter(Boolean), no_bid: [...noBid].filter(Boolean),
      timed_out: [...timedOut].filter(Boolean), errored: [...errored].filter(Boolean) });
  }
  return out;
})()
"""


def summarise(snapshots: list[dict]) -> dict:
    """Combine every Prebid instance on a page into one summary."""
    if not snapshots:
        return {"found": False}
    bids = [b for s in snapshots for b in s.get("bids", [])]
    won = [b for s in snapshots for b in s.get("won", [])]
    requested = sorted({x for s in snapshots for x in s.get("requested", [])})
    bidders_bid = sorted({b["bidder"] for b in bids if b.get("bidder")})
    top_per_unit: dict[str, float] = {}
    by_bidder: dict[str, dict] = defaultdict(lambda: {"bids": 0, "max_cpm": 0.0, "sum_cpm": 0.0})
    for b in bids:
        top_per_unit[b["unit"]] = max(top_per_unit.get(b["unit"], 0.0), b["cpm"])
        entry = by_bidder[b["bidder"]]
        entry["bids"] += 1
        entry["sum_cpm"] += b["cpm"]
        entry["max_cpm"] = max(entry["max_cpm"], b["cpm"])
    currencies = sorted({b["currency"] for b in bids if b.get("currency")})
    return {
        "found": True,
        "versions": sorted({s.get("version", "") for s in snapshots}),
        "ad_units": sum(s.get("ad_units", 0) for s in snapshots),
        "auctions": sum(s.get("auctions", 0) for s in snapshots),
        "bidders_requested": requested,
        "bidders_bid": bidders_bid,
        "timed_out": sorted({x for s in snapshots for x in s.get("timed_out", [])}),
        "errored": sorted({x for s in snapshots for x in s.get("errored", [])}),
        "bids": len(bids),
        "avg_cpm": round(sum(b["cpm"] for b in bids) / len(bids), 3) if bids else 0.0,
        "top_bid_sum": round(sum(top_per_unit.values()), 3),
        "units_with_bids": len(top_per_unit),
        "won": len(won),
        "won_sum": round(sum(b["cpm"] for b in won), 3),
        "currency": "/".join(currencies) or "",
        "by_bidder": {k: {**v, "sum_cpm": round(v["sum_cpm"], 3), "max_cpm": round(v["max_cpm"], 3)}
                      for k, v in sorted(by_bidder.items())},
    }
