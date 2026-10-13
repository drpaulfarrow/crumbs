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

**Switching a lane**
- Flipping a switch takes effect immediately: the lane closes its open connections so the browser reconnects through the new setting.

**Whole-PC lane**
- This lane is a real DNS server.
- `system-dns-on.ps1` points Windows at it; `system-dns-off.ps1` puts everything back.

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
| Publisher | 1557389 |
| Live placement | **22983564** |
| Ad units | leaderboard 728x90, medium rectangle 300x250, wide skyscraper 160x600 |
| Bidder / timeout | `appnexus`, 1000 ms |
| Keywords per ad unit | `genre=running`, `crumbs_demo=true` |

**Before relying on it:**
- **Check that 22983564 returns live bids.** On drpaulfarrow.com the "Mock Bids" toggle was on, so the prices shown there were mocked.
  - Turn mock off on that page first.
  - If you get no bids, set `"use_test_placement": true` to fall back to Prebid's public test placement 13144370. It always returns a sample ad.
- **Member ID 958** shown on that page is also the ID used in Prebid's sample responses. Bids here are requested by placement ID only, so it isn't needed.

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

## Whole-PC lane (optional, needs admin)

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

`static/vendor/prebid-11.41.0-appnexus.js` is Prebid.js 11.41.0 with only the Xandr adapter, bundled with esbuild from the npm package.
