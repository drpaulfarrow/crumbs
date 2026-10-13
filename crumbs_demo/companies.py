"""Map a domain to the company behind it, for the "who was tracking you" view."""

COMPANIES = {
    "google-analytics.com": "Google",
    "googletagmanager.com": "Google",
    "googlesyndication.com": "Google",
    "googleadservices.com": "Google",
    "doubleclick.net": "Google",
    "google.com": "Google",
    "gstatic.com": "Google",
    "app-measurement.com": "Google",
    "youtube.com": "Google",
    "facebook.net": "Meta",
    "facebook.com": "Meta",
    "instagram.com": "Meta",
    "bing.com": "Microsoft",
    "clarity.ms": "Microsoft",
    "adnxs.com": "Microsoft (Xandr)",
    "linkedin.com": "Microsoft (LinkedIn)",
    "amazon-adsystem.com": "Amazon",
    "scorecardresearch.com": "Comscore",
    "quantserve.com": "Quantcast",
    "quantcount.com": "Quantcast",
    "chartbeat.com": "Chartbeat",
    "chartbeat.net": "Chartbeat",
    "hotjar.com": "Hotjar",
    "hotjar.io": "Hotjar",
    "demdex.net": "Adobe",
    "omtrdc.net": "Adobe",
    "2o7.net": "Adobe",
    "everesttech.net": "Adobe",
    "adsrvr.org": "The Trade Desk",
    "rlcdn.com": "LiveRamp",
    "pippio.com": "LiveRamp",
    "liadm.com": "LiveIntent",
    "id5-sync.com": "ID5",
    "crwdcntrl.net": "Lotame",
    "bluekai.com": "Oracle",
    "krxd.net": "Salesforce",
    "agkn.com": "Neustar",
    "tapad.com": "Tapad",
    "criteo.com": "Criteo",
    "criteo.net": "Criteo",
    "taboola.com": "Taboola",
    "outbrain.com": "Outbrain",
    "rubiconproject.com": "Magnite",
    "pubmatic.com": "PubMatic",
    "openx.net": "OpenX",
    "casalemedia.com": "Index Exchange",
    "indexww.com": "Index Exchange",
    "smartadserver.com": "Equativ",
    "3lift.com": "TripleLift",
    "triplelift.com": "TripleLift",
    "mathtag.com": "MediaMath",
    "moatads.com": "Oracle (Moat)",
    "doubleverify.com": "DoubleVerify",
    "adsafeprotected.com": "IAS",
    "tiktok.com": "TikTok",
    "ads-twitter.com": "X",
    "snapchat.com": "Snap",
    "sc-static.net": "Snap",
    "pinterest.com": "Pinterest",
    "permutive.com": "Permutive",
    "permutive.app": "Permutive",
    "tealiumiq.com": "Tealium",
    "tiqcdn.com": "Tealium",
    "newrelic.com": "New Relic",
    "nr-data.net": "New Relic",
    "segment.com": "Twilio Segment",
    "segment.io": "Twilio Segment",
    "mixpanel.com": "Mixpanel",
    "amplitude.com": "Amplitude",
    "optimizely.com": "Optimizely",
    "teads.tv": "Teads",
    "media.net": "Media.net",
    "kargo.com": "Kargo",
    "the-ozone-project.com": "Ozone",
    "gumgum.com": "GumGum",
    "bouncex.net": "Wunderkind",
    "bounceexchange.com": "Wunderkind",
    "cdnwidget.com": "Wunderkind",
    "visualwebsiteoptimizer.com": "VWO",
    "go-mpulse.net": "Akamai",
    "akstat.io": "Akamai",
    "stackadapt.com": "StackAdapt",
    "adtrafficquality.google": "Google",
    "googlesyndication.com": "Google",
    "intentiq.com": "Intent IQ",
    "sharethrough.com": "Sharethrough",
    "lijit.com": "Sovrn",
    "openx.com": "OpenX",
    "pubmatic.com": "PubMatic",
    "adform.net": "Adform",
    "amazon.com": "Amazon",
}

# Two-label public suffixes, so t.dailymail.co.uk belongs to dailymail.co.uk, not "co.uk".
_TWO_LABEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp",
    "co.kr", "com.br", "com.mx", "com.tr", "co.in", "co.za", "com.sg", "com.hk", "com.cn",
}


def registrable_domain(host: str) -> str:
    labels = host.lower().rstrip(".").split(".")
    keep = 3 if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def company_for(domain: str) -> str:
    labels = domain.lower().rstrip(".").split(".")
    for i in range(len(labels) - 1):
        name = COMPANIES.get(".".join(labels[i:]))
        if name:
            return name
    return registrable_domain(domain)
