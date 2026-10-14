# Crumbs A/B demo

A working, switchable Crumbs setup for a live demo on a Windows laptop.

- **Two browser windows side by side.** Window A has Crumbs off and window B has Crumbs on. Each has its own switch in a control panel, with live counts of what was blocked and whose trackers they were.
- **"Crumbs on" uses the real Crumbs resolver** (eyeo's DNS servers from the Crumbs setup wizard). If that can't serve your network, it falls back to a local copy of EasyPrivacy, the list Crumbs is built on.
- **A test publisher page** runs a real Prebid.js auction against your Microsoft Monetize (Xandr) placement, with keyword targeting. It also reports which ad and tracker domains the device can reach. The same page works from the Android emulator running the Crumbs app.
- **An optional whole-PC lane** points Windows itself at the filter.

Background research for the case study is in [`research/RESEARCH_BRIEF.md`](research/RESEARCH_BRIEF.md).

## How it works

```
 Window A (Crumbs off) --proxy :8081--+                    +--> normal DNS (your router / 1.1.1.1)
                                      +--> Crumbs filter --+
 Window B (Crumbs on)  --proxy :8082--+    (decides per    +--> Crumbs resolver 2.152.74.48 / .254
                                      |     hostname)            (or local EasyPrivacy list)
 Whole PC (optional)   --DNS :53------+
                                      |
 Control panel + test page  http://127.0.0.1:5380
```

**Windows A and B**
- Each window is a fresh Chrome or Edge profile, launched with `--proxy-server` pointing at its own lane.
- The browser never resolves names itself. Every hostname goes through the filter, which is exactly what a DNS blocker sees.
- HTTPS stays end-to-end encrypted; the lane only sees hostnames.

**Live view of each window**
- The panel watches both windows through the browser's DevTools port (9231 for A, 9232 for B, loopback only).
- It shows the page each window has open, and every request with its full URL and outcome: OK, blocked by Crumbs, blocked by the browser itself, DNS failure, timeout.
- Windows open blank, and the panel then opens the pages, so even the first request is recorded.
- The A/B windows use **Edge** by default. Set `"browser": "chrome"` in `demo_config.json` to use Chrome instead.
- Edge's built-in tracking prevention blocks some trackers on its own, even in window A. Those requests show up as "blocked by the browser itself", not as Crumbs.

**Monetization seen in Prebid**
- Every 2 seconds the panel reads each window's Prebid.js results from the live page.
- It shows them per site, with A and B side by side:
  - bidders asked, bidders that bid, bids received;
  - the top bid per ad slot added up (a rough header-bidding value of the page view);
  - average bid, winning bids, and bidders that timed out or errored;
  - a per-bidder comparison.
- This works on any site running Prebid (the test page, and big news sites such as the Guardian and the Daily Mail).
- It covers header bidding only. Google AdX, direct deals and Amazon bids decide outside Prebid. CPMs are bids in the header auction, not final prices.

**Switching a lane**
- Flipping a switch takes effect immediately: the lane closes its open connections so the browser reconnects through the new setting.

**Whole-PC lane**
- This lane is a real DNS server.
- `system-dns-on.ps1` points Windows at it; `system-dns-off.ps1` puts everything back.

## Case-study page with the panel inside it

The demo also serves the case-study site at **http://127.0.0.1:5380/case-study**. Its "Live demo" tab shows the control panel, so you can present and demo from one page.

- Start the demo as usual, or with `--open-site` to open the case-study page instead of the bare panel.
- Put the case-study window on the left third of the screen.
- Use the "Open A/B" buttons in the Live demo tab. When the panel is inside the case-study page, the A/B windows open on the right two-thirds, leaving the page visible.
- `"site_share"` in `demo_config.json` sets how much of the screen's left side is kept free (default `0.34`).
- The file is `crumbs_demo/static/case-study.html`, a copy of the published case-study site.

## Updating

```powershell
git pull
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item demo_config.example.json demo_config.json -Force   # if you haven't customised it
```

## Setup (once)

1. Install **Python 3.10+** from python.org (tick "Add to PATH").
2. Install **Chrome or Edge**. Edge is already on Windows.
3. In PowerShell, from the repo folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
   ```
   This does five things:
   - creates `.venv` and installs the dependencies;
   - downloads fresh EasyPrivacy and EasyList (a 13 Oct 2026 snapshot is bundled as a fallback);
   - creates `demo_config.json`;
   - runs `check-crumbs`;
   - runs the tests.

### Check the Crumbs resolver from the network you'll demo on

```powershell
.venv\Scripts\python -m crumbs_demo check-crumbs
```

This prints how the normal DNS and the Crumbs resolver answer a few ordinary sites, trackers and ad servers.

**If it warns that Crumbs refused Wikipedia, the resolver probably only serves the public IP address it was set up for (your home).**
- Run this again on the meeting wifi before you rely on it.
- If it still fails there, start with `-Local` so "Crumbs on" uses the bundled EasyPrivacy list.
- Everything else works the same.

## Running the demo

```powershell
scripts\windows\start-demo.ps1              # windows open the real sites in demo_config.json
scripts\windows\start-demo.ps1 -Page test   # windows open the Prebid test page
scripts\windows\start-demo.ps1 -Local       # Crumbs on = local EasyPrivacy, not eyeo's resolver
```

The control panel opens at <http://127.0.0.1:5380/>. Its buttons reopen the A/B windows at any time, with fresh profiles each time.

**Suggested flow**
1. Open both windows on the same news site. Panel: B blocks dozens of tracker requests, grouped by company, while A blocks none.
2. Point out **"Ad domains still loading"** on B. Crumbs targets trackers, not ads, so the publisher still gets paid but loses cross-site identity.
3. Switch to the test page (`-Page test`). B's auction still clears on the page's keywords (contextual targeting), while the ID-sync and analytics probes show as blocked.
4. Flip B's switch off and press **Run again**. Everything comes back.
5. Show the same page on the emulator with the real Crumbs app on and off (below).

## Your Monetize placement and keyword targeting

`demo_config.example.json` already uses the setup from the drpaulfarrow.com Prebid test page:

| | |
|---|---|
| Member / publisher | 958 / 1557389 |
| Live placement | **22983564** |
| Ad units | leaderboard 728x90, medium rectangle 300x250, wide skyscraper 160x600 |
| Bidder / timeout | `appnexus`, 1000 ms |
| Keywords per ad unit | `genre=running`, `crumbs_demo=true` |

Set `"use_test_placement": true` to switch every unit to placement 13144370 instead.

**In Monetize:**
- Make sure placement 22983564 accepts all three sizes.
- Add line items targeting the key-value `genre=running` (or `crumbs_demo=true`), each with a creative and a CPM, so you control what wins.
- The test page runs on `127.0.0.1` / `10.0.2.2`. If the placement or line items are limited to drpaulfarrow.com, allow any domain for the demo.
- If the adapter has been renamed, change `bidder`.

## Real Crumbs app in the Android emulator

1. Install Android Studio. In Device Manager, create a phone with a **Google Play** system image and start it.
2. Sign in to Play and install **Crumbs: DNS Privacy**.
3. In the emulator's Chrome, go to Settings > Privacy > **Use secure DNS** and set it **off**, so lookups go through Crumbs.
4. Open `http://10.0.2.2:5380/test?lane=emulator`. `10.0.2.2` is the emulator's name for your laptop.
5. Toggle Crumbs in the app and press **Run again**.
   - The page infers whether Crumbs is on from what it can reach.
   - Every run appears in the panel's "Test page results" table.
   - The table records whether **Xandr's own domain (`ib.adnxs.com`) gets through real Crumbs**. If it doesn't, the auction fails outright.

## Warm profile: a realistic returning user

Fresh profiles look like brand-new users with no cookies, IDs or consent, and many bidders pass on them. To compare like with like:

1. In the panel, press **Warm-up browser**. A normal Edge window opens on a dedicated profile, with no proxy and no Crumbs.
2. Browse the sites you'll test for a few minutes and **accept the cookie banners**.
3. **Close that window**, so its cookies are saved.
4. With **"from warm profile"** ticked (the default once one exists), every A/B launch starts **both** windows as identical copies of it: same cookies, IDs and consent.

This deliberately does not copy your work or personal Edge profile. Those hold sign-in sessions, and the demo windows run with a debugging port that exposes cookies to local programs.

## Measuring at scale

```powershell
.venv\Scripts\python -m crumbs_demo measure --rounds 1     # first: a quick pass to prune sites without Prebid
.venv\Scripts\python -m crumbs_demo measure --rounds 10    # then the real run
.venv\Scripts\python -m crumbs_demo report results\<folder> # rebuild the report any time
```

**What a run does**
1. For each round, it opens two browsers from the warm profile: Crumbs off (A) and Crumbs on (B).
2. Both load the same page at the same moment and accept the cookie banner the same way.
3. Both scroll for 10 seconds, so lazy-loaded slots run their auctions, then wait 12 seconds.
4. It records the page's Prebid results, Google Ad Manager slot fill, and every request's outcome, grouped by company.

Site order is shuffled each round.

**Inputs and outputs**
- **Site list:** `crumbs_demo/data/sites_uk.txt` by default, or `--sites your_list.txt`.
- **Output:** `results/<timestamp>/`, containing:
  - `visits.jsonl`, the raw data;
  - `report.html`, the report;
  - `sites.csv`, `bidders.csv`, `companies.csv`.

**The report shows**
- **Publisher view:** header-bidding value per page view, A vs B, per site and on average, with a 95% range. Also bids, bidders that bid, and Ad Manager slots filled.
- **Ad-tech view:** each Prebid bidder's bid rate and typical top bid, with Crumbs off vs on.
- **Network view:** which companies' requests Crumbs blocked, and the share of ID-sync requests blocked.

**Timing:** a visit takes about 30 to 40 seconds, so 30 sites x 10 rounds is roughly 3 hours. It's safe to stop with Ctrl+C; partial results are kept.

**Limits**
- **It covers the Prebid share of revenue only.** Google AdX, direct deals and Amazon decide outside Prebid. Bids are offers, not final prices.
- **One machine, one IP address, one country.**
- **Automated browsers.** `--headless` is faster, but ad stacks may treat headless browsers differently.
- **Keep volumes modest.** Ads shown to automated browsers are invalid traffic that advertisers pay for. `--max-visits` (default 2,000) is a deliberate cap, and the tool never clicks ads.

## Whole-PC lane (optional, needs admin)

The Whole PC card says whether Windows is using the demo's DNS server.
- **Point Windows here (admin)** runs `system-dns-on.ps1` after a Windows admin prompt.
- **Restore Windows DNS (admin)** puts your DNS settings back.

The scripts can also be run by hand:

```powershell
# demo already running, in an admin PowerShell:
scripts\windows\system-dns-on.ps1
# ...flip "Whole PC" in the panel...
scripts\windows\system-dns-off.ps1
```

**Warning:** while Windows points at 127.0.0.1, stopping the demo means **no internet until you run `system-dns-off.ps1`**.

Chrome and Edge's "Use secure DNS" setting bypasses system DNS, so turn it off to see browser traffic in this lane.

## Limits worth knowing (and worth raising)

- **DNS sees domains, not URLs.**
  - EasyPrivacy blocks the Meta Pixel with a path rule (`connect.facebook.net/.../fbevents.js`), which DNS can't express, so a DNS-only blocker lets it through.
  - DNS can't hide ad slots on the page or allow some ads through while blocking others (Acceptable Ads works at that level).
  - Trackers served from the site's own domain are invisible to DNS, except when they're aliased to a tracker's domain (CNAME cloaking), which the filter catches.
- **Real Crumbs puts nothing in the bid request that this page can see or control.** Its opt-in interest groups live on eyeo's servers.
- **The Crumbs resolver may be tied to the network it was set up for.** Run `check-crumbs` on the day.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests
python -m crumbs_demo run --no-dns --crumbs-resolver local   # macOS/Linux: no admin port needed
```

`static/vendor/hb-11.41.0.js` is Prebid.js 11.41.0 with only the Xandr adapter, bundled with esbuild from the npm package. It has a neutral file name because ad-block filters match URLs containing "prebid".
