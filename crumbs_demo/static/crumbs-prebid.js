/* Crumbs module for Prebid.js: demo version.
 *
 * Works with any page's Prebid through public APIs only, so the demo can inject
 * it into real sites. A production version would be a Prebid RTD submodule.
 *
 * 1. Asks the Crumbs signal hostname for this user's group. Only the Crumbs
 *    resolver answers that name, so no answer means "not a Crumbs user" and the
 *    module does nothing.
 * 2. Crumbs mode for Crumbs users: no ID syncs, no device storage, and (where the
 *    page's Prebid build includes the activity controls module) no user IDs sent
 *    to bidders. Auctions still run, and the group below is still sent.
 * 3. Adds the opted-in group to every auction as a seller-defined audience
 *    (ortb2 user.data, IAB Audience Taxonomy 1.1, segtax 4), as an ortb2
 *    keyword (crumbs_grp=..., which the Xandr adapter passes as a key-value),
 *    and as a Google Ad Manager key-value.
 */
(function () {
  "use strict";
  if (window.top !== window || window.__crumbs) return;
  var cfg = Object.assign({
    signalUrl: "http://signal.crumbs.test:5390/group",
    timeoutMs: 600,
    keyword: "crumbs_grp",
  }, window.__crumbsCfg || {});

  var st = window.__crumbs = {
    version: "demo-1", status: "checking", group: null, provider: null,
    globals: [], crumbsMode: [], auctionsTagged: 0, gam: false, log: [],
  };
  function note(msg) { st.log.push(msg); try { console.info("[Crumbs] " + msg); } catch (e) {} }

  var signal = new Promise(function (resolve) {
    var done = false;
    var timer = setTimeout(function () { if (!done) { done = true; resolve(null); } }, cfg.timeoutMs);
    try {
      fetch(cfg.signalUrl + "?t=" + Date.now(), { cache: "no-store", credentials: "omit" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
        .then(function (j) { if (!done) { done = true; clearTimeout(timer); resolve(j); } });
    } catch (e) { resolve(null); }
  }).then(function (j) {
    if (j && j.crumbs === "on") {
      st.status = "on";
      st.provider = j.provider;
      st.group = j.group ? { key: j.group, label: j.label, taxonomy: j.taxonomy, sda: j.sda, arrivedOn: j.arrived_on } : null;
      note("Crumbs user. Group: " + (st.group ? st.group.label + " (segtax 4, id " + st.group.sda.id + ")" : "none, opted out"));
      tagGam();
    } else {
      st.status = "off";
      note("No Crumbs answer for the signal name: not a Crumbs user, module inactive.");
    }
    return st.status === "on" ? j : null;
  });

  function fragment(j) {
    if (!j || !j.group) return null;
    return {
      user: {
        data: [{ name: j.provider, ext: { segtax: j.sda.segtax }, segment: [{ id: j.sda.id }] }],
        keywords: cfg.keyword + "=" + j.group,
      },
    };
  }

  function crumbsMode(g) {
    g.setConfig({
      deviceAccess: false,
      userSync: { syncEnabled: false },
      // Takes effect where the page's Prebid includes the allowActivities module.
      allowActivities: {
        syncUser: { default: false },
        accessDevice: { default: false },
        transmitEids: { default: false },
        transmitPreciseGeo: { default: false },
      },
    });
    st.crumbsMode = ["ID syncs off", "device storage off", "user IDs off (with activity controls)"];
  }

  function tagGam() {
    var gt = window.googletag = window.googletag || { cmd: [] };
    gt.cmd = gt.cmd || [];
    gt.cmd.push(function () {
      try {
        if (st.group) { gt.pubads().setTargeting(cfg.keyword, st.group.key); st.gam = true; }
      } catch (e) {}
    });
  }

  function attach(g, name) {
    if (!g || g.__crumbsAttached) return;
    g.__crumbsAttached = true;
    st.globals.push(name);
    g.que = g.que || [];
    g.que.push(function () {
      signal.then(function (j) { if (j) crumbsMode(g); });
      if (g.requestBids && typeof g.requestBids.before === "function") {
        g.requestBids.before(function (next, opts) {
          signal.then(function (j) {
            if (j) {
              crumbsMode(g);  // again, in case the page changed userSync since
              var frag = fragment(j);
              if (frag) {
                opts = opts || {};
                var o = opts.ortb2 = opts.ortb2 || {};
                o.user = o.user || {};
                o.user.data = (o.user.data || []).concat(frag.user.data);
                o.user.keywords = o.user.keywords ? o.user.keywords + "," + frag.user.keywords : frag.user.keywords;
                st.auctionsTagged++;
              }
            }
            next(opts);
          });
        }, 100);
      } else {
        note("This Prebid version has no requestBids hook; only Crumbs mode applied.");
      }
    });
  }

  function scan() {
    var names = (window._pbjsGlobals || []).concat(["pbjs"]);
    for (var i = 0; i < names.length; i++) {
      var g = window[names[i]];
      if (g && typeof g === "object") attach(g, names[i]);
    }
  }
  // Most pages use "pbjs". Creating its queue now puts our hook ahead of the page's first auction.
  window.pbjs = window.pbjs || { que: [] };
  // Pages create their Prebid global at different times: keep looking for a while.
  scan();
  var tries = 0;
  var iv = setInterval(function () { scan(); if (++tries > 100) clearInterval(iv); }, 100);
})();
