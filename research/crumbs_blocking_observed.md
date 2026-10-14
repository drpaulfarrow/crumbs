# Ad-tech domains: what Crumbs blocked and allowed

Observed with the real Crumbs resolver (2.152.74.48 / .254) in window B of the A/B demo.
The pages were the Guardian, the Daily Mail and the Prebid test page, plus a 30-site measurement run.
Observed 13 to 14 Oct 2026. This is not a complete list of Crumbs' rules: it only covers domains these pages requested.

**Confidence**
- **Seen:** the exact hostname appeared in the live request list as "blocked by Crumbs", or as loaded OK.
- **Company only:** the measurement report showed blocks for that company, but not which hostnames.

## The pattern

Crumbs mostly blocks per subdomain, not per company:
- **ID-sync subdomains are blocked**, while the same companies' bidding subdomains still work. Index, Magnite, The Trade Desk, Criteo, TripleLift, Amazon and Lotame all follow this pattern.
- **The exceptions cost revenue.** For Xandr, Ozone and Kargo, and for Magnite's server-side Prebid, the auction endpoint itself is blocked, so those bidders drop out completely.

## Blocked

| Company | Hostname | What it does | Confidence |
|---|---|---|---|
| Microsoft (Xandr) | `ib.adnxs.com` | **Auction** (Prebid `/ut/v3/prebid`), plus `/getuid` | Seen |
| Microsoft (Xandr) | `acdn.adnxs.com` | User-sync page | Seen |
| Microsoft (Xandr) | `secure.adnxs.com` | Segment pixel (`/seg`) | Seen |
| Ozone | `elb.the-ozone-project.com` | **Auction** (`/openrtb2/auction`) | Seen |
| Kargo | `krk2.kargo.com` | **Auction** (`/api/v1/prebid`) and event logging | Seen |
| Magnite | `prebid-server.rubiconproject.com` | **Server-side Prebid auction** | Seen |
| Magnite | `eus.rubiconproject.com` | User sync (`usync.html`) | Seen |
| The Trade Desk | `match.adsrvr.org` | ID sync (`/track/usersync`, `/track/rid`) | Seen |
| Index Exchange | `js-sec.indexww.com` | ID match (`ixmatch.html`) | Seen |
| TripleLift | `eb2.3lift.com` | User sync | Seen |
| Criteo | `gum.criteo.com` | Sync frame | Seen |
| PubMatic | `image6.pubmatic.com` | Cookie sync (`UCookieSetPug`) | Seen |
| Amazon | `aax-eu.amazon-adsystem.com` | ID sync (`/s/iu3`) | Seen |
| Lotame | `bcp.crwdcntrl.net` | Audience data / ID map | Seen |
| LiveRamp | `check.analytics.rlcdn.com`, `idsync.rlcdn.com` | ID check and sync | Seen |
| Comscore | `sb.scorecardresearch.com` | Audience measurement beacon | Seen |
| IAS | some `adsafeprotected.com` hosts | Ad verification | Company only |
| ID5 | `id5-sync.com` hosts | Universal ID | Company only |
| EUID (The Trade Desk) | `euid.eu` | European Unified ID | Company only |
| Eyeota | `eyeota.net` | Audience data | Company only |
| Microsoft (LinkedIn) | LinkedIn ads hosts | Conversion tracking | Company only |
| Quantcast | some `quantserve.com` hosts | Measurement / audiences | Company only, partly blocked |
| Taboola | some Taboola hosts | Recommendations / tracking | Company only, partly blocked |
| Others | `anonymised.io`, `pbxai.com`, `geoedge.be`, `nodals.io` | ID, ad security, data | Company only |
| Adobe | `typekit.net` | **Web fonts** (likely collateral damage) | Company only |
| Google | some Google hosts | Unidentified | Company only |

## Allowed (loaded OK with Crumbs on)

**Prebid bidding endpoints**

| Company | Hostname |
|---|---|
| Index Exchange | `htlb.casalemedia.com` |
| Criteo | `grid-bidder.criteo.com` |
| The Trade Desk | `direct.adsrvr.org` (OpenPath bidding) |
| Magnite | `fastlane.rubiconproject.com` (client-side bidding) |
| OpenX | `rtb.openx.net` |
| PubMatic | `hbopenbid.pubmatic.com` |
| Teads | `a.teads.tv` |
| TripleLift | `tlx.3lift.com`. Not blocked, but the page sometimes cancelled it at the Prebid timeout |

**Amazon**

| Hostname | What it does |
|---|---|
| `web-banner.ads.aps.amazon-adsystem.com` | Bidding |
| `c.amazon-adsystem.com` | `apstag.js` |
| `config.aps.amazon-adsystem.com` | Configuration |

**Google**

| Hostname | What it does |
|---|---|
| `securepubads.g.doubleclick.net` | Google Ad Manager |
| `pagead2.googlesyndication.com`, `tpc.googlesyndication.com` | Ad serving |
| `ep1/ep2.adtrafficquality.google` | Ad traffic quality |
| `fundingchoicesmessages.google.com` | Google's consent tool |
| `csi.gstatic.com` | Performance logging |
| `www.google-analytics.com`, `www.googletagmanager.com` | Analytics and tags: reachable in the test-page check |

**Trackers and ID or data providers**

| Company | Hostname | Note |
|---|---|---|
| Meta | `www.facebook.com/tr` | Meta Pixel endpoint |
| Meta | `connect.facebook.net` | Pixel script |
| Permutive | `api.permutive.app` | Audience data |
| Wunderkind (BounceX) | `events.bouncex.net`, `api.bounceexchange.com`, `ids.cdnwidget.com` | Includes a `deviceID` call |
| VWO | `dev.visualwebsiteoptimizer.com`, `r2.visualwebsiteoptimizer.com` | A/B testing and tracking |
| Lotame | `tags.crwdcntrl.net` | Tag script. The data call `bcp.` is blocked |
| Shared ID (pubcid) | `secure.cdn.fastclick.net` | |
| Akamai | `c.go-mpulse.net` | Real-user monitoring |
| Duration Media | `be.durationmedia.net` | |
| Criteo | `static.criteo.net` | Publisher tag. Reachable in the test-page check |
