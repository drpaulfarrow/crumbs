"""Turn a measure run (visits.jsonl) into report.html plus CSVs.

Every number is a paired comparison: the same page, loaded at the same moment,
with Crumbs off (A) and on (B). Changes are computed per site first and then
averaged across sites, so a few big sites don't dominate and currencies never
get mixed.
"""

from __future__ import annotations

import csv
import html
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

BOOTSTRAP = 2000


def load(path: Path) -> list[dict]:
    path = path / "visits.jsonl" if path.is_dir() else path
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def pair_up(rows: list[dict]) -> list[tuple[dict, dict]]:
    by_key: dict[tuple, dict] = defaultdict(dict)
    for r in rows:
        by_key[(r["round"], r["site"])][r["lane"]] = r
    return [(v["off"], v["on"]) for v in by_key.values() if "off" in v and "on" in v]


def metrics(r: dict) -> dict:
    p, g, req = r.get("prebid", {}), r.get("gpt", {}), r.get("requests", {})
    found = p.get("found", False)
    return {
        "prebid_found": found,
        "hb_value": p.get("top_bid_sum", 0.0) if found else 0.0,
        "bids": p.get("bids", 0) if found else 0,
        "bidders_bid": len(p.get("bidders_bid", [])) if found else 0,
        "slots_with_bid": p.get("units_with_bids", 0) if found else 0,
        "gam_filled": g.get("filled", 0) if g.get("found") else 0,
        "gam_slots": g.get("slots", 0) if g.get("found") else 0,
        "blocked_by_crumbs": req.get("crumbs", 0),
        "sync_ok": r.get("sync", {}).get("ok", 0),
        "sync_blocked": r.get("sync", {}).get("crumbs", 0),
        "currency": p.get("currency", ""),
    }


def _ci(values: list[float], rng: random.Random) -> tuple[float, float] | None:
    if len(values) < 3:
        return None
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP))
    return means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]


def analyse(rows: list[dict], seed: int = 7) -> dict:
    rng = random.Random(seed)
    pairs = pair_up(rows)
    by_site: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for a, b in pairs:
        by_site[a["host"]].append((metrics(a), metrics(b)))

    sites = []
    for host, ms in sorted(by_site.items()):
        hb_a = [a["hb_value"] for a, _ in ms]
        hb_b = [b["hb_value"] for _, b in ms]
        mean_a, mean_b = statistics.fmean(hb_a), statistics.fmean(hb_b)
        diffs = [b - a for a, b in zip(hb_a, hb_b)]
        ci = _ci(diffs, rng)
        sites.append({
            "host": host, "pairs": len(ms),
            "prebid_share": sum(a["prebid_found"] or b["prebid_found"] for a, b in ms) / len(ms),
            "currency": next((a["currency"] for a, _ in ms if a["currency"]), ""),
            "hb_a": mean_a, "hb_b": mean_b,
            "hb_change": (mean_b / mean_a - 1) if mean_a > 0 else None,
            "hb_diff_ci": ci,
            **{f"{k}_a": statistics.fmean(a[k] for a, _ in ms) for k in
               ("bids", "bidders_bid", "slots_with_bid", "gam_filled", "blocked_by_crumbs", "sync_ok")},
            **{f"{k}_b": statistics.fmean(b[k] for _, b in ms) for k in
               ("bids", "bidders_bid", "slots_with_bid", "gam_filled", "blocked_by_crumbs", "sync_ok", "sync_blocked")},
        })

    # Headline: mean of per-site relative changes, sites with Prebid value in A.
    # Bootstrap resamples whole sites (pairs on a site are not independent).
    measurable = [s for s in sites if s["hb_change"] is not None]
    site_pairs = {s["host"]: by_site[s["host"]] for s in measurable}

    def site_change(ms):
        a = statistics.fmean(x["hb_value"] for x, _ in ms)
        b = statistics.fmean(y["hb_value"] for _, y in ms)
        return b / a - 1 if a > 0 else 0.0

    headline = None
    if measurable:
        changes = [s["hb_change"] for s in measurable]
        boot = []
        hosts = list(site_pairs)
        for _ in range(BOOTSTRAP):
            sample = [site_pairs[h] for h in rng.choices(hosts, k=len(hosts))]
            # resample pairs within each sampled site too
            boot.append(statistics.fmean(site_change(rng.choices(ms, k=len(ms))) for ms in sample))
        boot.sort()
        headline = {"change": statistics.fmean(changes), "ci": (boot[int(0.025 * BOOTSTRAP)],
                                                                 boot[int(0.975 * BOOTSTRAP) - 1]),
                    "sites": len(measurable), "pairs": sum(len(m) for m in site_pairs.values())}

    def rel(key):
        a = sum(s[f"{key}_a"] for s in measurable)
        b = sum(s[f"{key}_b"] for s in measurable)
        return (b / a - 1) if a else None

    # Ad-tech view: per Prebid bidder, across all paired visits where it was asked.
    bidders: dict[str, dict] = defaultdict(lambda: {lane: {"asked": 0, "bid": 0, "cpms": []} for lane in ("off", "on")})
    for a, b in pairs:
        for row in (a, b):
            p = row.get("prebid", {})
            if not p.get("found"):
                continue
            for name in p.get("bidders_requested", []):
                bidders[name][row["lane"]]["asked"] += 1
            for name, e in p.get("by_bidder", {}).items():
                bidders[name][row["lane"]]["bid"] += 1
                bidders[name][row["lane"]]["cpms"].append(e["max_cpm"])
    bidder_rows = []
    for name, lanes in bidders.items():
        row = {"bidder": name}
        for lane, d in lanes.items():
            row[f"asked_{lane}"] = d["asked"]
            row[f"bid_rate_{lane}"] = d["bid"] / d["asked"] if d["asked"] else None
            row[f"top_cpm_{lane}"] = statistics.fmean(d["cpms"]) if d["cpms"] else None
        bidder_rows.append(row)
    bidder_rows.sort(key=lambda r: -(r["asked_off"] + r["asked_on"]))

    # Network view: requests Crumbs blocked, per company, per paired visit.
    company: dict[str, dict] = defaultdict(lambda: {"ok_off": 0, "ok_on": 0, "blocked_on": 0})
    for a, b in pairs:
        for row, lane in ((a, "off"), (b, "on")):
            for name, kind, n in row.get("by_company", []):
                if kind == "ok":
                    company[name][f"ok_{lane}"] += n
                elif kind == "crumbs" and lane == "on":
                    company[name]["blocked_on"] += n
    n_pairs = max(len(pairs), 1)
    company_rows = sorted(({"company": k, **{f: v / n_pairs for f, v in d.items()}} for k, d in company.items()
                           if d["blocked_on"]), key=lambda r: -r["blocked_on"])

    sync_ok_a = sum(m["sync_ok"] for ms in by_site.values() for m, _ in ms)
    sync_b_ok = sum(m["sync_ok"] for ms in by_site.values() for _, m in ms)
    sync_b_blocked = sum(m["sync_blocked"] for ms in by_site.values() for _, m in ms)

    return {
        "pairs": len(pairs), "sites": sites, "headline": headline,
        "bids_change": rel("bids"), "bidders_change": rel("bidders_bid"),
        "slots_change": rel("slots_with_bid"), "gam_fill_change": rel("gam_filled"),
        "sync": {"off_ok": sync_ok_a / n_pairs, "on_ok": sync_b_ok / n_pairs, "on_blocked": sync_b_blocked / n_pairs},
        "bidders": bidder_rows, "companies": company_rows,
    }


# --- output -------------------------------------------------------------------

def _pct(v, signed=True):
    if v is None:
        return "–"
    return f"{v * 100:+.0f}%" if signed else f"{v * 100:.0f}%"


def _num(v, digits=2):
    return "–" if v is None else f"{v:.{digits}f}"


def write_csvs(result: dict, out: Path) -> None:
    with open(out / "sites.csv", "w", newline="", encoding="utf-8") as f:
        fields = [k for k in result["sites"][0] if k != "hb_diff_ci"] + ["hb_diff_ci_low", "hb_diff_ci_high"] \
            if result["sites"] else []
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for s in result["sites"]:
            ci = s.get("hb_diff_ci") or (None, None)
            w.writerow({**{k: v for k, v in s.items() if k != "hb_diff_ci"},
                        "hb_diff_ci_low": ci[0], "hb_diff_ci_high": ci[1]})
    with open(out / "bidders.csv", "w", newline="", encoding="utf-8") as f:
        if result["bidders"]:
            w = csv.DictWriter(f, fieldnames=list(result["bidders"][0]))
            w.writeheader()
            w.writerows(result["bidders"])
    with open(out / "companies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["company", "ok_off", "ok_on", "blocked_on"])
        w.writeheader()
        w.writerows(result["companies"])


def _diverging_rows(items: list[tuple[str, float | None, str]]) -> str:
    """Horizontal bars around a zero line; negative = red, positive = blue."""
    scale = max([abs(v) for _, v, _ in items if v is not None] + [0.05])
    out = []
    for label, v, tip in items:
        if v is None:
            bar = '<span class="na">no Prebid value in A</span>'
        else:
            width = abs(v) / scale * 50
            side = "neg" if v < 0 else "pos"
            pos = f"right:50%" if v < 0 else "left:50%"
            bar = (f'<span class="bar {side}" style="{pos};width:{width:.1f}%"></span>'
                   f'<span class="val {side}" style="{"right" if v < 0 else "left"}:calc(50% + {width:.1f}% + 6px)">'
                   f'{_pct(v)}</span>')
        out.append(f'<div class="drow" title="{html.escape(tip)}"><span class="dlabel">{html.escape(label)}</span>'
                   f'<span class="dtrack"><span class="zero"></span>{bar}</span></div>')
    return "\n".join(out)


def _paired_bars(rows: list[dict]) -> str:
    out = []
    for r in rows:
        cells = []
        for lane in ("off", "on"):
            v = r.get(f"bid_rate_{lane}")
            w = 0 if v is None else v * 100
            cells.append(f'<span class="pbar {lane}" style="width:{w:.1f}%"></span>'
                         f'<span class="pval">{_pct(v, signed=False)}</span>')
        tip = (f'{r["bidder"]}: asked {r["asked_off"]}/{r["asked_on"]} times; '
               f'avg top bid {_num(r["top_cpm_off"])} vs {_num(r["top_cpm_on"])}')
        out.append(f'<div class="prow" title="{html.escape(tip)}"><span class="dlabel">{html.escape(r["bidder"])}</span>'
                   f'<span class="pcells"><span class="pline">{cells[0]}</span><span class="pline">{cells[1]}</span></span></div>')
    return "\n".join(out)


def write_html(result: dict, run: dict, out: Path) -> Path:
    h = result["headline"]
    headline = (f'{_pct(h["change"])}' if h else "–")
    ci = (f'95% range {_pct(h["ci"][0])} to {_pct(h["ci"][1])} · {h["sites"]} sites · {h["pairs"]} paired page views'
          if h else "Not enough sites with Prebid bids in A yet.")
    site_items = [(s["host"], s["hb_change"],
                   f'{s["host"]}: {_num(s["hb_a"])} vs {_num(s["hb_b"])} {s["currency"]} per page view, {s["pairs"]} pairs')
                  for s in sorted(result["sites"], key=lambda s: (s["hb_change"] is None, s["hb_change"] or 0))]
    site_table = "".join(
        f'<tr><td>{html.escape(s["host"])}</td><td class="num">{s["pairs"]}</td>'
        f'<td class="num">{_pct(s["prebid_share"], False)}</td>'
        f'<td class="num">{_num(s["hb_a"])}</td><td class="num">{_num(s["hb_b"])}</td>'
        f'<td class="num">{_pct(s["hb_change"])}</td><td class="num">{html.escape(s["currency"])}</td>'
        f'<td class="num">{_num(s["bids_a"], 1)} → {_num(s["bids_b"], 1)}</td>'
        f'<td class="num">{_num(s["bidders_bid_a"], 1)} → {_num(s["bidders_bid_b"], 1)}</td>'
        f'<td class="num">{_num(s["gam_filled_a"], 1)} → {_num(s["gam_filled_b"], 1)}</td>'
        f'<td class="num">{_num(s["blocked_by_crumbs_b"], 0)}</td></tr>' for s in result["sites"])
    company_table = "".join(
        f'<tr><td>{html.escape(c["company"])}</td><td class="num">{c["blocked_on"]:.1f}</td>'
        f'<td class="num">{c["ok_off"]:.1f}</td><td class="num">{c["ok_on"]:.1f}</td></tr>'
        for c in result["companies"][:25])
    bidders = [b for b in result["bidders"] if b["asked_off"] + b["asked_on"] >= 4][:20]
    sync = result["sync"]
    blocked_share = sync["on_blocked"] / (sync["on_blocked"] + sync["on_ok"]) if (sync["on_blocked"] + sync["on_ok"]) else None

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crumbs Monetization Impact</title>
<style>
:root {{ --surface:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink2:#52514e; --muted:#7a7974; --line:#e6e5e0;
  --neutral:#f0efec; --neg:#e34948; --pos:#2a78d6; --off:#2a78d6; --on:#eb6834; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --surface:#1a1a19; --card:#232321;
  --ink:#f0efec; --ink2:#c3c2b7; --muted:#9a998f; --line:#383835; --neutral:#383835; --neg:#e66767; --pos:#3987e5;
  --off:#3987e5; --on:#d95926; }} }}
:root[data-theme="dark"] {{ --surface:#1a1a19; --card:#232321; --ink:#f0efec; --ink2:#c3c2b7; --muted:#9a998f;
  --line:#383835; --neutral:#383835; --neg:#e66767; --pos:#3987e5; --off:#3987e5; --on:#d95926; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--surface); color:var(--ink); font:14px/1.5 system-ui,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:28px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:32px 0 8px; }}
.sub {{ color:var(--ink2); margin:0; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-top:20px; }}
.tile {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.tile .v {{ font-size:30px; font-weight:700; font-variant-numeric:tabular-nums; }}
.tile .k {{ color:var(--ink2); font-size:13px; }} .tile .s {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; overflow-x:auto; }}
.drow, .prow {{ display:grid; grid-template-columns:220px 1fr; gap:10px; align-items:center; min-height:26px; }}
.dlabel {{ font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink); }}
.dtrack {{ position:relative; height:18px; }}
.zero {{ position:absolute; left:50%; top:-4px; bottom:-4px; width:1px; background:var(--line); }}
.bar {{ position:absolute; top:3px; height:12px; }}
.bar.neg {{ background:var(--neg); border-radius:4px 0 0 4px; }} .bar.pos {{ background:var(--pos); border-radius:0 4px 4px 0; }}
.val {{ position:absolute; top:0; font-size:12px; color:var(--ink2); font-variant-numeric:tabular-nums; }}
.na {{ position:absolute; left:calc(50% + 8px); font-size:12px; color:var(--muted); }}
.pcells {{ display:flex; flex-direction:column; gap:2px; }}
.pline {{ display:flex; align-items:center; gap:6px; }}
.pbar {{ height:9px; border-radius:0 4px 4px 0; min-width:1px; }} .pbar.off {{ background:var(--off); }} .pbar.on {{ background:var(--on); }}
.pval {{ font-size:12px; color:var(--ink2); font-variant-numeric:tabular-nums; }}
.legend {{ display:flex; gap:16px; font-size:12px; color:var(--ink2); margin-bottom:8px; }}
.sw {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
th {{ color:var(--ink2); font-weight:600; font-size:12px; }} .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.notes li {{ color:var(--ink2); margin-bottom:4px; }}
@media (max-width:640px) {{ .drow, .prow {{ grid-template-columns:110px 1fr; }} }}
</style></head><body><main>
<h1>Crumbs monetization impact</h1>
<p class="sub">Paired A/B page views: each page loaded at the same moment with Crumbs off (A) and on (B).
Crumbs on = {html.escape(str(run.get("crumbs", "?")))} · warm profile: {"yes" if run.get("warm_profile") else "no"} ·
{result["pairs"]} paired visits.</p>

<div class="tiles">
  <div class="tile"><div class="k">Publisher header-bidding value per page view</div><div class="v">{headline}</div>
    <div class="s">{ci}</div></div>
  <div class="tile"><div class="k">Prebid bids per page view</div><div class="v">{_pct(result["bids_change"])}</div>
    <div class="s">sites with Prebid value in A</div></div>
  <div class="tile"><div class="k">Bidders bidding per page view</div><div class="v">{_pct(result["bidders_change"])}</div>
    <div class="s">sites with Prebid value in A</div></div>
  <div class="tile"><div class="k">ID-sync requests blocked with Crumbs on</div><div class="v">{_pct(blocked_share, False)}</div>
    <div class="s">{sync["on_blocked"]:.1f} blocked vs {sync["on_ok"]:.1f} allowed per page view</div></div>
</div>

<h2>Change in header-bidding value, by site (B vs A)</h2>
<div class="card">{_diverging_rows(site_items) or '<p class="sub">No paired visits yet.</p>'}</div>

<h2>Ad-tech companies: how often each Prebid bidder bid when asked</h2>
<div class="card"><div class="legend"><span><span class="sw" style="background:var(--off)"></span>Crumbs off (A)</span>
<span><span class="sw" style="background:var(--on)"></span>Crumbs on (B)</span></div>
{_paired_bars(bidders) or '<p class="sub">No bidder data yet.</p>'}</div>

<h2>Requests Crumbs blocked, by company (per paired page view)</h2>
<div class="card"><table><thead><tr><th>Company</th><th class="num">Blocked (B)</th>
<th class="num">Loaded (A)</th><th class="num">Loaded (B)</th></tr></thead><tbody>{company_table}</tbody></table></div>

<h2>Per site</h2>
<div class="card"><table><thead><tr><th>Site</th><th class="num">Pairs</th><th class="num">Prebid seen</th>
<th class="num">HB value A</th><th class="num">HB value B</th><th class="num">Change</th><th class="num">Cur.</th>
<th class="num">Bids A → B</th><th class="num">Bidders A → B</th><th class="num">GAM filled A → B</th>
<th class="num">Blocked (B)</th></tr></thead><tbody>{site_table}</tbody></table></div>

<h2>How to read this</h2>
<ul class="notes">
<li>Header-bidding value = the best Prebid bid per ad slot per auction, added up per page view. It is the Prebid share of
revenue only: Google AdX, direct deals and Amazon decide outside Prebid. Bids are offers in the header auction, not final prices.</li>
<li>The headline is the average of per-site changes, with a 95% range from resampling sites and page views (bootstrap).
Sites where A had no Prebid value are left out of it.</li>
<li>One machine, one IP address and one country; automated browsers; small samples per site. Treat it as directional.</li>
</ul>
</main></body></html>"""
    path = out / "report.html"
    path.write_text(page, encoding="utf-8")
    return path


def build_report(results: Path) -> Path:
    results = Path(results)
    out = results if results.is_dir() else results.parent
    run_file = out / "run.json"
    run = json.loads(run_file.read_text(encoding="utf-8")) if run_file.exists() else {}
    result = analyse(load(results))
    write_csvs(result, out)
    (out / "summary.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return write_html(result, run, out)
