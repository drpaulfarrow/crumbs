# Review: does Crumbs' blocking match what Crumbs is trying to do?

Crumbs' stated aim has two parts:
1. **Remove cross-site tracking.**
2. **Keep advertising working, and keep it personalised,** using Crumbs' own privacy-safe signal instead of trackers (opt-in interest groups and privacy-protected measurement).

This review checks the observed blocking (see `crumbs_blocking_observed.md`) against both parts.

It rests on a handful of A/B page views and one short 30-site run, so treat it as directional. Crumbs' rules may also differ by account.

## Verdict

Today's DNS blocking only partly achieves part 1, and does nothing for part 2.
- It blocks a lot of ID syncing, which is right.
- It also blocks some auctions outright, which costs revenue without a matching privacy gain.
- It lets several of the largest trackers and most identifiers straight through.
- No Crumbs signal reaches the ad auction, so the ads that remain are less targeted, not "personalised without trackers".

**Observed net effect**

| | Effect |
|---|---|
| Publishers | Header-bidding value per page view down 32% to 100% on every measured site |
| Bidding | Bidders that bid down about two thirds |
| Privacy | About 70% of ID-sync calls blocked; big identity flows untouched |

Publishers pay much of the cost, and the privacy gain is incomplete.

## 1. Blocks that fit the goal

These are cheap in revenue and meaningful for privacy.

**ID syncing between ad-tech companies.** This is how a user's identity spreads across the ad ecosystem, and it's exactly what Crumbs should stop.
- The Trade Desk `match.adsrvr.org`
- Magnite `eus.rubiconproject.com/usync`
- Index `ixmatch`
- TripleLift `eb2.3lift.com/sync`
- Criteo `gum.criteo.com`
- PubMatic cookie sync
- Amazon `aax-eu…/iu3`
- Xandr user sync and segment pixels

**Data brokers and ID providers:** Lotame `bcp.crwdcntrl.net`, LiveRamp, Eyeota, ID5, EUID.

**The cost:** bidders recognise the user less often, so they bid less or pass. We saw The Trade Desk and Criteo bid less with Crumbs on. That is the intended trade, but it only pays off if Crumbs puts a replacement signal back in (section 4).

## 2. Blocks that don't fit: revenue lost without a matching privacy gain

### Auction endpoints blocked outright
- Xandr `ib.adnxs.com/ut/v3/prebid`
- Ozone `elb.the-ozone-project.com/openrtb2/auction`
- Kargo `krk2.kargo.com/api/v1/prebid`
- Magnite's server-side Prebid `prebid-server.rubiconproject.com`

**Why this is a problem:**
- **These are the auctions themselves, not trackers.** Blocking them removes the bidder from the page entirely.
  - On the Guardian, Ozone was the top bidder ($3.00 CPM); with Crumbs on it was gone.
  - Ozone is a UK publisher-owned ad platform, so this hits UK news publishers directly.
- **The privacy logic isn't consistent.** These requests carry the same kinds of identifiers as the auction requests Crumbs allows (Index, OpenX, PubMatic, Magnite client-side, The Trade Desk direct). Blocking some auctions and not others doesn't change what the user leaks overall. It changes **who gets paid**.
- **That raises a neutrality problem for eyeo.** Eyeo sells Acceptable Ads and Blockthrough to this same industry, and Microsoft and Google are reported Acceptable Ads payers. A privacy product that removes Xandr's auction while leaving Google's ad stack untouched invites the "pay to play" criticism eyeo already faces.

### Ad verification blocked (IAS)
- Verification tells advertisers whether an ad was viewable, brand-safe and not fraudulent. Many brands only buy verified inventory.
- Blocking it makes Crumbs users' impressions harder to sell at full price.
- Verification is a privacy question only to the extent it fingerprints users; mostly it doesn't. A privacy-safe path for verification makes more sense than blocking it.

### Audience measurement blocked (Comscore)
- Comscore figures are the currency publishers use to sell their audience.
- Blocking it undercounts Crumbs users in publishers' audited numbers. That's an indirect revenue cost, and it isn't really cross-site profiling.

### Collateral breakage
- Adobe `typekit.net` web fonts were blocked. That's a site-quality cost for users with no privacy upside worth the breakage.

## 3. Gaps: tracking that still gets through

| What | Where it was seen | Why it matters |
|---|---|---|
| **Meta Pixel** | `connect.facebook.net`, `www.facebook.com/tr` | The largest cross-site tracker on the web. It shares a domain with Facebook itself, so DNS can't block it without breaking Facebook |
| **Google Analytics, Tag Manager** | Reachable in the test-page check | Google's analytics and tag loading |
| **IDs stored by the site and sent in bid requests** | With Crumbs on: Magnite's client-side bid URL carried `eid_pubcid.org=…`; Google Ad Manager requests carried `a3p=…` with SharedID/pubcid, Criteo, ID5, Lotame and others, plus Permutive IDs (`puid`, `prmtvvid`) | Stopping the sync calls doesn't stop IDs the page already stored. They ride inside the bid requests to the auctions that are still allowed, **including Google's** |
| **Device and visitor IDs** | Wunderkind `ids.cdnwidget.com?deviceID=…`, VWO visitor IDs, Permutive audience segments | Identity and profiling that pass straight through |

**The net effect for Google:** a Crumbs user's identity mostly still reaches Google, through Ad Manager and IDs stored on the site, while some independent auctions are cut off. That is the opposite of the "open web, private by design" position eyeo is aiming for.

## 4. Part 2 (personalised ads without trackers) isn't happening yet

- Nothing from Crumbs appears in any bid request: no interest group, no audience, no deal ID. DNS can't add data to a request.
- So buyers simply see a less identifiable user. That means fewer bidders and lower prices. It's privacy by subtraction, not substitution.
- Crumbs 2.0's opt-in interest groups and privacy-protected measurement exist on eyeo's side, but nothing connects them to Prebid or Ad Manager on the page.

## What a tailored version would look like

1. **Block identity, not commerce.** Write a clear policy and apply it to every company equally:

   | Type of endpoint | Policy |
   |---|---|
   | Auctions and ad serving | Allow |
   | ID syncs, data brokers, cross-site analytics | Block |
   | Verification and measurement | Allow a privacy-safe version |

   Publish it like the Acceptable Ads standard, so it's predictable and defensible.

2. **Steer instead of block, with partners.**
   - Rather than blocking `ib.adnxs.com`, Crumbs DNS could send it to Xandr's existing cookieless endpoint (`ib.adnxs-simple.com`).
   - The same could apply to any company that offers a no-ID endpoint.
   - Companies that comply get through; those that don't are blocked. That's Acceptable Ads leverage, applied to privacy.

3. **Close the gaps DNS can't reach**, using a component inside the page or the browser:
   - **Publisher side:** a "Crumbs mode" in the publisher's Prebid setup. Blockthrough already runs inside publisher wrappers, so it could detect Crumbs users and switch off ID modules and stored IDs for them.
   - **User side:** eyeo's browser SDK or extension strips `user.eids`/`eid_*`, Meta Pixel calls and analytics beacons.

4. **Deliver the "personalised" half.** Put Crumbs' signal into the auction:
   - **Cohort signal:** an opt-in interest-group ID (groups of 100+ people, privacy-protected) added through a Prebid real-time-data module as seller-defined audience data. How the page gets the cohort is an open design question. One option: an endpoint that only Crumbs' resolver can reach, so the resolver's knowledge of the household (from Crumbs' account linking) never leaves eyeo.
   - **Curated deals:** curated deal IDs that let buyers target Crumbs cohorts by name.
   - **Measurement:** privacy-protected attribution from Crumbs replaces the blocked pixels, so advertisers still get measurement.

   This is what turns "fewer, cheaper bids" into "fewer trackers, still-valuable bids".

5. **Measure it.** Re-run the paired measurement for each policy change:
   - with the auction endpoints unblocked;
   - with steering to cookieless endpoints;
   - with a cohort signal (simulated on the test page).

   The target result: ID syncs blocked, identifiers absent from bid requests, and header-bidding value close to the Crumbs-off level.

## Publishers as Crumbs' biggest advocates

### The argument
- **For publishers, a user with no signals is a user they can't sell well.**
  - More and more of their traffic arrives with no usable identity: Safari and Firefox block third-party cookies; people refuse consent; ad blocking is growing (about 1.1B users); privacy laws keep tightening.
  - That traffic sells at a steep discount, or not at all.
- **Crumbs can turn some of that traffic back into an audience buyers will pay for:** opt-in interest groups of 100+ people, privacy-protected measurement, and curated deals, all attached to the publisher's own inventory.
- **So publishers gain twice:**
  - their audiences are worth more where signals have gone;
  - the alternative, more and more traffic with no signal, keeps losing value.
- **Publishers also have what Crumbs lacks.** Eyeo's own design doc for Crumbs named install base as its biggest risk:
  - direct relationships with hundreds of millions of readers;
  - consent and messaging screens they control;
  - a voice with buyers and regulators.
- **That makes them the natural people to recommend Crumbs.** The message is "Browse privately with Crumbs and keep supporting the journalism you read". That's a better offer to readers than "pay or accept tracking".

### The precondition: today's Crumbs would make publishers opponents, not advocates
- In our runs, Crumbs **cut** header-bidding value on every measured publisher (32% to 100%).
- It blocked Ozone, the UK publishers' own ad platform.
- Publishers will only advocate once Crumbs:
  1. stops blocking auctions and steers to cookieless endpoints instead;
  2. puts its interest-group signal and measurement into the auction;
  3. can show the uplift with numbers.

  These are the steps in "What a tailored version would look like" above.
- Eyeo also carries baggage with publishers: Acceptable Ads was called "extortion", and Trestle "holding our sites to ransom". So the terms have to be visibly fair: a revenue share and no pay-to-play.

### Use the right baseline when pitching publishers
- Our A/B compares a Crumbs user against a **fully tracked** user, which overstates what publishers lose.
- A Crumbs user's realistic alternative is usually:
  - an ad-blocker user, worth roughly nothing;
  - someone who refused consent, worth very little;
  - a Safari or Firefox user with no identity, discounted.
- **The pitch to publishers is "Crumbs traffic vs your other traffic with no signal", not "vs tracked traffic".** The measurement tool should add that comparison: a third window with no consent, or with an ordinary ad blocker, alongside Crumbs with its signal.

### How to enlist them
1. **Make launch partners of the publishers Crumbs currently hurts.**
   - Ozone and its UK publisher members (the Guardian, Reach and others) are the obvious first cohort-deal partners.
   - Today they are the most visible casualties, so they would make the most credible advocates.
2. **Use Blockthrough as the delivery route.** Blockthrough already runs inside publishers' ad code and already shows messages to ad-blocking readers. It can:
   - read the Crumbs signal and pass it into Prebid;
   - report the uplift on Crumbs traffic in the publisher's own dashboard;
   - show readers a "Browse with Crumbs" invitation. That grows Crumbs' user base through publishers rather than eyeo's own marketing.
3. **Share the value.** Give publishers a share of the extra revenue that Crumbs signals bring (eyeo's own Crumbs design doc envisaged rewarding the sites visited), and show it transparently.
4. **Give them proof to repeat.** Run per-publisher paired measurements showing value recovered on traffic with no signal, which publishers can take to buyers and trade bodies.
5. **Form a coalition.** Publishers, plus the independent ad-tech companies that follow the "block identity, not commerce" standard. Together they can argue for privacy-safe audiences with buyers, the IAB and regulators. That positions eyeo as the open web's privacy partner rather than its tollkeeper.

### What to measure to show publishers it works
- Prebid and ad-server value per page view: Crumbs-with-signal traffic vs the publisher's other traffic with no signal.
- Share of traffic buyers can target, before and after.
- Fill rate and bid density on Crumbs traffic.
- Reader take-up of the "Browse with Crumbs" invitation (the growth channel).
- Publisher revenue share paid out.

## Questions to put to eyeo
- Is the current blocklist a deliberate policy (for example, "anything EasyPrivacy lists"), or inherited from filter lists? Who decides which auction endpoints are blocked?
- How does Crumbs think about competitive neutrality between Google and independent ad-tech companies, given Acceptable Ads relationships?
- What's the plan for getting the interest-group signal into Prebid and Ad Manager? Is Blockthrough the delivery route?
- Is DNS meant to be the long-term enforcement layer, or the distribution layer (routers, phones), with request-level privacy handled by eyeo's browser SDK?
- Are publishers part of Crumbs' go-to-market today? Would Blockthrough be the route for getting the Crumbs signal into publishers' ad code, and for publishers recommending Crumbs to their readers?
