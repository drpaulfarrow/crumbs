# eyeo Monetization Lead Case Study: Research Brief

Prepared 13 Oct 2026. Research came from four parallel tracks: eyeo the company, Crumbs, the 2026 ad ecosystem, and monetization models. Note the limits:

- Most web pages could not be fetched directly in this environment, so many figures come from search summaries.
- The Crumbs technical detail is first-hand. It comes from reading eyeo's public GitLab source code.
- Items marked **[verify]** rest on weak or conflicting sources.

---

## 1. TL;DR: the 10 things that matter

1. **eyeo makes most of its money from Acceptable Ads (AA).** Revenue was about €86M in 2024 and flat versus 2023. AA is on by default for ad-block users.
   - About 90% of allowlisted entities pay nothing.
   - "Large entities" pay about 30% of the *incremental* revenue that allowlisting brings them. A large entity gains more than 10M extra monthly impressions.
   - Reported payers include Google, Microsoft, Amazon, Criteo and Taboola. A critic claims Google pays only about 1-2%. **[verify]**
2. **The company was "re-founded" on 28 July 2025.**
   - Douglas de Jager became CEO. He founded spider.io (ad fraud), which Google bought.
   - About 40% of staff were cut.
   - The new mission is to make online advertising **"private by design"**. That means blocking third-party tracking, cookie syncing and fingerprinting by default, plus privacy-preserving (differential privacy) measurement for advertisers.
   - The "profitable core" stays: ABP, AdBlock, AA and Blockthrough.
3. **CPO: Vegard Johnsen.** He spent about 10 years at Google leading ad-block recovery, consent management and Funding Choices. Expect him in the room, and expect deep knowledge of the publisher recovery side. Status in 2026 is not fully confirmed.
4. **Crumbs is the probable subject (the repo name).** It has had two lives:
   - **Crumbs 1.0 (2021-23)** was a privacy extension.
     - It built an on-device interest profile.
     - It sent 3 random, k-anonymity-checked interest IDs plus country in an `x-crumbs-interests` HTTP header, only to partner domains.
     - It never got OpenRTB/Prebid plumbing or named SSP/DSP partners.
     - It has been in maintenance since Nov 2023.
   - **Crumbs 2.0 (2026)** is **"Crumbs: DNS Privacy"**, a device-wide DNS tracker and malware blocker for Android and iOS (iOS since Aug 2026).
     - It has opt-in ad features: DP attribution, and "broad interest groups" of at least 100 users with noise added.
     - It appears to be a soft launch with no public metrics.
5. **There is a live monetization signal.** ABP 4.46.0 (6 Oct 2026) is testing a **Crumbs banner in place of the Premium upsell banner**. eyeo is choosing between a subscription upsell and growing the Crumbs base.
6. **The AA user base is growing in the wrong places.**
   - About 1.1B ad-blocking users (Q4 2025). Mobile is up; desktop is down 4%.
   - Low and middle-income markets are up 23%; high-income markets are down 14%.
   - 96% keep AA on, but that figure measures a default, not a preference.
   - **Net effect: more users, lower ARPU mix.**
7. **The AAC ad-refresh amendment (Aug 2026)** came out of an A/B test on about 49.5M ABP users. It is a direct yield lever (more impressions per AA pageview) and shows that eyeo runs large monetization experiments. The final decision is unknown.
8. **The privacy tailwind faded inside Chrome.**
   - Google kept third-party cookies (2024-25) and is retiring Privacy Sandbox APIs, including Topics and Protected Audience (announced Oct 2025).
   - Post-cookie urgency now exists mainly in Safari, Firefox and EU traffic.
   - This removes Google as a competitor in privacy-preserving targeting, but it also removes the forcing function.
9. **AI is shrinking the open web.**
   - AI Overviews cut organic clicks by about 40% when they appear.
   - Google referrals to news sites fell about a third.
   - ChatGPT ads launched Feb 2026 at about a $60 CPM.
   - Agentic browsers (Comet, Gemini in Chrome) see no ads.
   - The inventory AA monetizes is structurally shrinking, and new surfaces are emerging.
10. **There is an internal cannibalization tension.** "Private by design" (blocking cookie syncing and IDs) lowers the value of the AA and Blockthrough inventory that pays the bills. That is the strategic knot a Monetization Lead has to untie.

---

## 2. eyeo: company facts

| Item | Detail |
|---|---|
| HQ / offices | Cologne (HQ), Berlin, Toronto (Blockthrough), New York |
| Founded | 2011, by Till Faida and Wladimir Palant |
| Headcount | About 300 before July 2025, about 160-190 now **[verify]** |
| Ownership | Private, no known VC |
| CEO | Douglas de Jager (since Jul 2025; CTO from late 2024) |
| CPO | Vegard Johnsen (since Aug 2023, NYC, ex-Google ad-block recovery and consent) |
| Other | Goswijn Thijssen, MD User Business (Jan 2025). "VP Monetization" has been held by Igor Netto and Maciej Wicha; the current holder is unclear |

**Revenue (EUR)**

| Year | Revenue | Source |
|---|---|---|
| 2019 | ~47M | Profit 17.9M |
| 2020 | 55.8M | |
| 2021 | 62.9M | Net income 17.7M |
| 2022 | 71.2M | **[verify]** |
| 2023 | 87.2M | **[verify]** |
| 2024 | 86.1M | **[verify]** |

The 2022-24 figures come from an analyst table based on German Bundesanzeiger filings.

**Products**
- **Adblock Plus (ABP):** extensions for every major browser, plus a Premium tier priced at $1.99/mo or $19.99/yr per eyeo's site (third parties say $4/mo or $40/yr). Premium blocks annoyances (cookie banners, popups, floating video), not more ads.
- **AdBlock:** acquired 2021, about 64M Chrome users.
- **Adblock Browser:** Android and iOS.
- **Crumbs:** see section 3.
- **Browser Ad-Filtering Solution / Chromium SDK:** for OEM browsers. It avoids MV3 limits. Named partners are Aloha, Santa and Carbon. Opera "employs AA" on unknown terms.
- **Blockthrough:** acquired Nov 2022, with AAX merged in. It provides publisher ad-block recovery: serving AA-compliant ads to blockers and ad-block analytics, and claims more than $175M recovered.
- **AA Marketplaces (2023):** PMPs reaching about 250M ad-filtering users across 3,500 properties (Raptive, Fandom).
- **Trestle DSP (2021):** a US agency buying tool, status unknown. Publishers called it "ransom".
- **Flattr:** a micropayments service, acquired 2017 and **shut down 2023**. It is the cautionary tale for non-ad monetization.

**Acceptable Ads Standard (key rules)**
- Ads may sit above, beside or below primary content; ads placed in the middle of content are treated as intrusive.
- Ads must be labeled and visually distinct from content.
- Size caps:
  - above content: 200px high;
  - beside: 350px wide;
  - below: 400px high.
- Ads may take at most 15% of the visible page above the fold and 25% below.
- No pop-ups, autoplay sound or video, or animation.
- Governance: the independent Acceptable Ads Committee (since 2017) owns the standard and eyeo enforces it. There has been an "AA without third-party tracking" opt-in since 2017.

**Legal tail risk:** in July 2025 the BGH (Germany's Federal Court of Justice) sent Axel Springer's *copyright* claim against ABP back to the Hamburg court. Whether ad blocking unlawfully "modifies" website code is open again.

**Competitors and their models**

| Competitor | Model |
|---|---|
| uBlock Origin | Free, volunteer-run. Its full version is out of Chrome after MV3; uBO Lite remains |
| AdGuard | Paid apps and DNS/VPN |
| Ghostery | Contributions; privacy brand |
| Brave | Opt-in on-device ads, 70% to users in BAT. About 126M MAU (Aug 2026) and over $100M ARR **[verify]** |
| Opera | Native blocker plus search and ads. ARPU $2.49/MAU, a useful benchmark ceiling |
| Recovery vendors (Admiral, Ad-Shield) | Compete with Blockthrough. Admiral takes about 30% of recovered revenue |

---

## 3. Crumbs deep dive

### Crumbs 1.0 (launched Jan 2021, maintenance since Nov 2023)

It was a free Chrome/Firefox extension and was also built into Adblock Browser.

**Privacy features:**
- tracker blocking (EasyPrivacy);
- third-party cookie expiry;
- **email relay**;
- an IP-masking proxy for ad requests only (removed Nov 2023, likely for cost);
- tracking-parameter stripping;
- GPC (Global Privacy Control) on by default;
- cookie-banner denial;
- fingerprint shield.

**Ad side.** The design doc is *SPECTACLE*, at gitlab.com/eyeo/lab/spectacle. Read it before the meeting.
- **Profile:** about 9.2k domains are mapped to interest categories, weighted by dwell time, with 7%/day decay. There is an optional 90-day history cold start.
- **Taxonomy:** the docs say IAB, but the code looks derived from Google Cloud NL categories (about 544-621 nodes).
- **Disclosure:**
  - The header `x-crumbs-interests: {country, interests:[3 ids]}` goes only to domains on `crumbs.org/partners-v2.json`.
  - The interests are random picks from the user's strong interests, intersected with a server "safe-to-share" k-anonymous list.
  - Segment sizes are estimated with local differential privacy (RAPPOR).
- **No user ID**, so there is no frequency capping, sequencing or attribution. SPECTACLE itself listed these risks: fraud (clients can lie about segments), lack of verification, and **"needs a sufficiently large install base."**
- **There was never an OpenRTB or Prebid module.** The desktop sharing API was still a `TODO`. Defaults differed: sharing was opt-out in the extension terms and opt-in on Android.
- **It anticipated Google Topics by a year** and used almost the same mechanism, minus Chrome's distribution.

### Crumbs 2.0, "Crumbs: DNS Privacy" (2026)

- **How it works:** encrypted DNS to an eyeo resolver, via a local VPNService on Android. It blocks tracker, malware and phishing domains at device level. Logs are deleted in 24h.
- **Opt-in ad features (privacy policy, Sept 2026):**
  - **Attribution:** ad-performance measurement.
  - **Broad interest groups:** at least 100 users, with random noise members. Advertisers see only a DP-protected group ID. Interest flags "never leave" eyeo. Ad events are deleted after 30 days. eyeo says it measures its own campaigns this way.
- **Distribution:** cross-sell from ABP (the 4.46 banner test). No launch PR, no metrics.

### Why Crumbs 1.0 stalled, and what 2.0 must solve
- **Supply:** a separate install with no distribution beyond eyeo's own surfaces. 2.0 leads with user value (device-wide protection) and borrows the ABP base.
- **Demand:** a proprietary header and partner allowlist meant bespoke integration, and buyers still had cookies. 2.0 needs packaging buyers already understand (curated deals/PMPs via SSPs, DP measurement reports).
- **Measurement:** the lack of an ID broke attribution. 2.0 makes DP attribution a first-class product, and possibly the wedge.
- **Trust:** "the ad blocker sells your interests" is the critique to pre-empt. Opt-in, transparency and user benefit at the moment of monetization are the answer.

---

## 4. Ad ecosystem primer (2026)

**Supply chain:** advertiser, agency, **DSP** (Trade Desk, DV360, Amazon), **SSP/exchange** (AdX, Magnite, PubMatic, Index, Equativ, OpenX), header bidding (**Prebid**), publisher ad server (**GAM**), impression.

**Supporting standards:**
- **OpenRTB 2.6** is the bid protocol. Audience data goes in `user.data` / `user.eids`.
- **ads.txt, sellers.json and SupplyChain** provide supply-chain transparency.
- **Identity** options are UID2 (hashed email), RampID and ID5.
- **Clean rooms** (AWS, Snowflake, LiveRamp, ADH) match first-party data between parties.
- **Curation** (packaging audience plus supply at the SSP) is the most likely route for Crumbs cohorts to reach buyers.

**Take rates:**
- Trade Desk: about 20%.
- AdX: about 20%.
- SSPs: about 10-20%.
- ANA: only about 45% of programmatic spend becomes a quality impression.

**Growth:** it is in CTV and retail/commerce media. Open-web display, the inventory ad blocking touches, is flat (Magnite display about +2%; CTV +36%).

**Key metrics**

| Metric | Definition |
|---|---|
| CPM | Cost per 1,000 impressions, as the buyer sees it |
| eCPM | Revenue ÷ impressions × 1000, across pricing models |
| RPM | Publisher revenue per 1,000 pageviews or sessions |
| Fill | Filled ÷ requests |
| Sell-through | Sold ÷ available inventory |
| Viewability (MRC) | At least 50% of pixels for at least 1s (display) or 2s (video) |
| CTR | Clicks ÷ impressions, about 0.1% for display |

**Privacy Sandbox**
- Cookie deprecation was cancelled in 2024, and the user-choice prompt was dropped in Apr 2025.
- In Oct 2025 Google announced the retirement of Topics, Protected Audience, Attribution Reporting and others. CHIPS, FedCM and Private State Tokens stay.
- Safari 26 turns on Advanced Fingerprinting Protection for all browsing. Firefox has Total Cookie Protection.

**Regulation**
- **US v Google (ad tech), Brinkema:**
  - Remedies ruling, 2 Sept 2026: **no divestiture**, but behavioral remedies.
  - Google loses first look and last look, and Unified Pricing Rules for indirect deals.
  - **AdX must bid into Prebid.**
  - A monitor is appointed, for 6 years.
  - These are modest sell-side tailwinds.
- **EU:** a €2.95B ad tech fine (Sept 2025), with divestiture still on the table.
- **Search case (Mehta):** Chrome stays with Google, and exclusive deals are banned. MV3 remains Google's call.
- **DMA:** Meta's €200M "pay or consent" fine led to a "less personalised ads" option from Jan 2026.
- **TCF:** the TC String is personal data (May 2025).
- **US:** 20 state privacy laws, about 12 requiring **GPC**. Browser-level user signals now carry legal weight, which is an opening for eyeo.

**AI disruption**
- Fewer clicks reach publishers (see TL;DR 9).
- **ChatGPT ads:** launched Feb 2026 at about a $60 CPM, with self-serve and international rollout following. A claimed $1B run rate is **[verify]**.
- **Google:** ads in AI Overviews and AI Mode.
- **Perplexity:** exited ads and launched Comet Plus, which shares 80% of revenue with publishers.
- **Agentic browsing:**
  - OpenAI Atlas launched Oct 2025 and was shut down Aug 2026.
  - Comet blocks ads by default.
  - Gemini in Chrome auto-browse is rolling out.
  - Agents generate no billable impressions and look like invalid traffic.
- **Crawl payments:** Cloudflare offers Pay-Per-Crawl, now moving to "Pay Per Use". Licensing deals (OpenAI, Microsoft PCM) go to big publishers only.

**Ad blocking and MV3**
- Chrome has fully removed MV2. ABP shipped MV3 early (May 2024), so MV3 hurt eyeo less than uBO and nudged users toward compliant blockers.
- YouTube is moving to SSAI (server-side ad insertion).
- Publishers are moving ad stacks server-side.
- Browser-level blocking now reaches less of the stack.

---

## 5. Monetization playbook reference

**Revenue tree**
Revenue = users × % AA-enabled × AA impressions per user × fill × eCPM × eyeo take rate
+ Premium subscribers × ARPPU
+ OEM/SDK licensing and revenue share
+ (new) Crumbs cohort and measurement revenue.

Cut every term by **geo tier**, **platform** (desktop/mobile) and **channel** (owned extension vs partner browser).

**Benchmarks**
- **ARPU:** Opera $2.49 per MAU per year (browser with search and ads, the ceiling). Mozilla about $570M, about 85% from Google, which is a concentration warning.
- **Freemium to paid:** 2-5% typical. Extensions are likely below 1-2% because a free substitute and the default AA are "good enough" (inference).
- **Consumer subscription Y1 retention:** median about 40%.
- **Google Offerwall** (rewarded ad, survey or micropayment): about 9% average uplift. contentpass (EU ad-free pass) costs about €3.99/mo.

**Cautionary tales**
- **Honey (PayPal), 2024-26:** it overwrote affiliate cookies, lost about 7M users and faced lawsuits. Chrome Web Store then required affiliate links to be disclosed, user-initiated and of direct user benefit. Principle: **monetize only at a moment of explicit user benefit.**
- **Flattr:** micropayments never scaled.
- **Brave Rewards:** falling payouts erode the user-side promise.

**Marketplace framing (three-sided):**
- **Users:** trust; AA keep-on rate is the trust KPI.
- **Publishers:** recovered revenue; they defect to anti-adblock walls if the take rate is too high.
- **Advertisers/ad tech:** demand; they need scale, measurement and familiar plumbing.

**Guardrail metrics**
- uninstall rate;
- AA opt-out rate;
- store rating;
- support tickets;
- Crumbs opt-in rate and opt-out after the first ad.

---

## 6. Glossary (terms in this space)

| Term | Meaning |
|---|---|
| AA / AAC | Acceptable Ads / Acceptable Ads Committee |
| Allowlisting | Exempting compliant ads from blocking |
| Ad recovery | Showing compliant ads to ad-block users on a publisher's behalf |
| DSP / SSP / GAM / AdX | Buy-side platform / sell-side platform / Google's ad server / Google's exchange |
| Prebid / header bidding | Open-source, client- or server-side auction run before the ad server |
| OpenRTB | IAB bid-request protocol |
| PMP / curated deal | Private marketplace; packaged supply plus audience sold via deal IDs |
| Clean room | Privacy-safe environment for joining two parties' data |
| Topics / Protected Audience | Google Privacy Sandbox interest-targeting and remarketing APIs (being retired) |
| k-anonymity | Every shared attribute set is shared by at least k users |
| Differential privacy (DP) | Calibrated noise so individuals can't be inferred from outputs |
| RAPPOR | Google's local-DP technique for counting from clients |
| GPC | Global Privacy Control browser signal; legally binding opt-out in about 12 US states |
| TCF | IAB Europe consent framework (TC String) |
| MV3 / DNR | Chrome Manifest V3 / declarativeNetRequest (rule-capped blocking API) |
| SSAI | Server-side ad insertion (stitched into content, hard to block) |
| eCPM / RPM / ARPU / ARPPU | See section 4 |

---

## 7. Gaps to verify, and things to ask in the meeting

**Gap in the brief itself:** the case study says "some of the problems we're working on" but names none. Either a second page is missing, or framing the problem is part of the test. If the latter, **Crumbs 2.0 go-to-market and monetization** is the most likely intended topic.

**Verify before quoting:**
- 2022-24 revenue;
- the current CPO;
- the outcome of the AA ad-refresh amendment;
- the Crumbs 2.0 install base and opt-in rate;
- whether Trestle still exists;
- Opera's AA terms;
- the eyeo report's mobile growth figure (+27% vs +42%).

**Good questions to put to the room**
1. What does Crumbs need to prove in the next 12 months: user growth, opt-in rate, or advertiser revenue per opted-in user?
2. Is DP measurement a standalone B2B product, sellable without targeting scale, or only an enabler for cohorts?
3. How do you think about "private by design" lowering the value of AA and Blockthrough inventory? Is that cannibalization budgeted?
4. Crumbs banner vs Premium banner: what is the decision metric? LTV per user? Strategic base-building?
5. Distribution: owned cross-sell vs OEM/telco bundling. Which partners care about privacy as a differentiator (Samsung, telcos, EU browsers)?
6. Should eyeo propose an "Acceptable Ads for AI / agents" standard as answer engines and agents become new blocking surfaces?
