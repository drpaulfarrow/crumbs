"""End-to-end tests against fake upstream DNS and a fake website, all on loopback."""

import asyncio
import json
import socket

from dnslib import CNAME, QTYPE, RCODE, RR, A, DNSRecord

from crumbs_demo.blocklist import Blocklists, DomainSet, parse_rules
from crumbs_demo.control import ControlServer
from crumbs_demo.dns_server import start_dns
from crumbs_demo.engine import Engine, Lane
from crumbs_demo.proxy import LaneProxy
from crumbs_demo.upstream import Upstream, is_sinkholed


# Not 127.0.0.1: filtering resolvers use that as a "blocked" answer.
SITE_IP = "127.0.0.2"


def free_port(kind=socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeDns(asyncio.DatagramProtocol):
    """Answers every name with SITE_IP. Names in `sinkhole` get 0.0.0.0 (a filtering resolver)."""

    def __init__(self, sinkhole=(), nxdomain=False):
        self.sinkhole = set(sinkhole)
        self.nxdomain = nxdomain
        self.queries = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        req = DNSRecord.parse(data)
        name = str(req.q.qname).rstrip(".")
        self.queries.append(name)
        reply = req.reply()
        if self.nxdomain:
            reply.header.rcode = RCODE.NXDOMAIN
        elif name == "cloaked.news.example":
            reply.add_answer(RR(req.q.qname, QTYPE.CNAME, rdata=CNAME("metrics.google-analytics.com."), ttl=60))
            reply.add_answer(RR("metrics.google-analytics.com.", QTYPE.A, rdata=A(SITE_IP), ttl=60))
        elif req.q.qtype == QTYPE.A:
            ip = "0.0.0.0" if name in self.sinkhole else SITE_IP
            reply.add_answer(RR(req.q.qname, QTYPE.A, rdata=A(ip), ttl=60))
        self.transport.sendto(reply.pack(), addr)


async def start_fake_dns(**kw):
    port = free_port(socket.SOCK_DGRAM)
    proto = FakeDns(**kw)
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: proto, local_addr=("127.0.0.1", port))
    return transport, proto, f"127.0.0.1:{port}"


async def start_website():
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello")
        await writer.drain()
        writer.close()
    port = free_port()
    server = await asyncio.start_server(handle, SITE_IP, port)
    return server, port


def lists():
    trackers = DomainSet.from_text("||google-analytics.com^\n||facebook.net^\n")
    ads = DomainSet.from_text("||adnxs.com^\n")
    return Blocklists(trackers, ads, {"trackers": "test", "ads": "test"})


async def connect_via(proxy_port: int, host: str, port: int) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
    status = await reader.readuntil(b"\r\n\r\n")
    if b" 200 " not in status.split(b"\r\n")[0]:
        writer.close()
        return status
    writer.write(f"GET / HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
    body = await asyncio.wait_for(reader.read(), 5)
    writer.close()
    return status + body


# --- block lists ----------------------------------------------------------------

def test_parse_rules_keeps_only_dns_enforceable_rules():
    blocked, exceptions = parse_rules(
        "! comment\n"
        "||tracker.com^\n"
        "||third.com^$script,third-party\n"  # DNS can't tell; block the domain
        "||only-on-spiegel.com^$domain=spiegel.de\n"
        "||popup.com^$popup\n"
        "||path.com/pixel\n"
        "@@||ok.tracker.com^\n"
        "0.0.0.0 hosts-style.net\n"
        "plain-domain.org\n"
    )
    assert blocked == {"tracker.com", "third.com", "hosts-style.net", "plain-domain.org"}
    assert exceptions == {"ok.tracker.com"}


def test_domain_set_matches_subdomains_and_exceptions():
    ds = DomainSet({"tracker.com"}, {"ok.tracker.com"})
    assert ds.match("a.b.tracker.com") == "tracker.com"
    assert ds.match("TRACKER.COM.") == "tracker.com"
    assert ds.match("ok.tracker.com") is None
    assert ds.match("nottracker.com") is None


def test_bundled_seed_lists_load():
    bl = Blocklists.load()
    assert bl.classify("www.google-analytics.com").category == "tracker"
    assert bl.classify("ib.adnxs.com").category == "ad"
    assert bl.classify("www.wikipedia.org").category == "other"


def test_sinkhole_detection():
    q = DNSRecord.question("x.com")
    r = q.reply()
    r.add_answer(RR("x.com", QTYPE.A, rdata=A("0.0.0.0")))
    assert is_sinkholed(r)
    r2 = q.reply()
    r2.add_answer(RR("x.com", QTYPE.A, rdata=A("93.184.216.34")))
    assert not is_sinkholed(r2)


# --- proxy lanes ----------------------------------------------------------------

def test_proxy_lane_blocks_trackers_only_when_on():
    async def run():
        dns_t, _, dns_addr = await start_fake_dns()
        site, site_port = await start_website()
        engine = Engine(lists(), upstream=Upstream([dns_addr], os_fallback=False))
        lane = engine.add_lane(Lane("b", "B", "proxy", free_port(), enabled=True))
        proxy = LaneProxy(engine, lane)
        await proxy.start()
        try:
            blocked = await connect_via(lane.port, "www.google-analytics.com", site_port)
            assert b"403" in blocked and b"google-analytics.com" in blocked
            allowed = await connect_via(lane.port, "news.example", site_port)
            assert allowed.endswith(b"hello")
            ad = await connect_via(lane.port, "ib.adnxs.com", site_port)
            assert ad.endswith(b"hello"), "ads are classified, not blocked, by default"

            engine.set_enabled("b", False)
            assert (await connect_via(lane.port, "www.google-analytics.com", site_port)).endswith(b"hello")

            s = lane.stats
            assert s.blocked == 1 and s.requests == 4
            assert s.blocked_companies.most_common(1)[0][0] == "Google"
            assert "adnxs.com" in s.ad_domains_seen
        finally:
            proxy.server.close()
            site.close()
            dns_t.close()
    asyncio.run(run())


def test_proxy_lane_catches_cname_cloaking():
    async def run():
        dns_t, _, dns_addr = await start_fake_dns()
        site, site_port = await start_website()
        engine = Engine(lists(), upstream=Upstream([dns_addr], os_fallback=False))
        lane = engine.add_lane(Lane("b", "B", "proxy", free_port(), enabled=True))
        proxy = LaneProxy(engine, lane)
        await proxy.start()
        try:
            out = await connect_via(lane.port, "cloaked.news.example", site_port)
            assert b"403" in out
            assert "CNAME cloak" in lane.stats.recent[-1]["note"]
        finally:
            proxy.server.close()
            site.close()
            dns_t.close()
    asyncio.run(run())


def test_crumbs_resolver_mode_follows_crumbs_verdicts():
    async def run():
        normal_t, _, normal_addr = await start_fake_dns()
        crumbs_t, crumbs, crumbs_addr = await start_fake_dns(sinkhole={"ib.adnxs.com", "unlisted-tracker.io"})
        site, site_port = await start_website()
        engine = Engine(lists(), upstream=Upstream([normal_addr], os_fallback=False),
                        crumbs=Upstream([crumbs_addr], os_fallback=False))
        lane_on = engine.add_lane(Lane("b", "B", "proxy", free_port(), enabled=True))
        lane_off = engine.add_lane(Lane("a", "A", "proxy", free_port(), enabled=False))
        proxies = [LaneProxy(engine, lane_on), LaneProxy(engine, lane_off)]
        for p in proxies:
            await p.start()
        try:
            # Crumbs decides, not the local list: the local tracker list doesn't matter here...
            assert (await connect_via(lane_on.port, "www.google-analytics.com", site_port)).endswith(b"hello")
            # ...and Crumbs can block what the local list wouldn't.
            assert b"403" in await connect_via(lane_on.port, "ib.adnxs.com", site_port)
            assert b"403" in await connect_via(lane_on.port, "unlisted-tracker.io", site_port)
            # Crumbs off: Crumbs' resolver isn't consulted at all.
            before = len(crumbs.queries)
            assert (await connect_via(lane_off.port, "ib.adnxs.com", site_port)).endswith(b"hello")
            assert len(crumbs.queries) == before
            assert lane_on.stats.recent[-1]["source"] == "Crumbs resolver"
        finally:
            for p in proxies:
                p.server.close()
            site.close()
            normal_t.close()
            crumbs_t.close()
    asyncio.run(run())


def test_toggle_drops_open_tunnels():
    async def run():
        dns_t, _, dns_addr = await start_fake_dns()
        hold = asyncio.Event()

        async def slow(reader, writer):
            await hold.wait()
            writer.close()
        site_port = free_port()
        site = await asyncio.start_server(slow, SITE_IP, site_port)
        engine = Engine(lists(), upstream=Upstream([dns_addr], os_fallback=False))
        lane = engine.add_lane(Lane("a", "A", "proxy", free_port(), enabled=False))
        proxy = LaneProxy(engine, lane)
        await proxy.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", lane.port)
            writer.write(f"CONNECT www.google-analytics.com:{site_port} HTTP/1.1\r\n\r\n".encode())
            assert b"200" in await reader.readuntil(b"\r\n\r\n")
            engine.set_enabled("a", True)
            assert await asyncio.wait_for(reader.read(), 2) == b""  # closed by the toggle
        finally:
            hold.set()
            proxy.server.close()
            site.close()
            dns_t.close()
    asyncio.run(run())


# --- system DNS lane ------------------------------------------------------------

async def ask(port: int, name: str, qtype="A") -> DNSRecord:
    loop = asyncio.get_running_loop()
    fut = loop.create_future()

    class P(asyncio.DatagramProtocol):
        def connection_made(self, t):
            t.sendto(DNSRecord.question(name, qtype).pack())

        def datagram_received(self, data, addr):
            fut.set_result(data)
    t, _ = await loop.create_datagram_endpoint(P, remote_addr=("127.0.0.1", port))
    try:
        return DNSRecord.parse(await asyncio.wait_for(fut, 3))
    finally:
        t.close()


def test_dns_lane_sinkholes_trackers_and_forwards_the_rest():
    async def run():
        dns_t, _, dns_addr = await start_fake_dns()
        engine = Engine(lists(), upstream=Upstream([dns_addr], os_fallback=False))
        lane = engine.add_lane(Lane("system", "S", "dns", free_port(socket.SOCK_DGRAM), enabled=True))
        closers = await start_dns(engine, lane, ["127.0.0.1"])
        try:
            r = await ask(lane.port, "www.google-analytics.com")
            assert [str(x.rdata) for x in r.rr] == ["0.0.0.0"]
            r = await ask(lane.port, "www.google-analytics.com", "AAAA")
            assert [str(x.rdata) for x in r.rr] == ["::"]
            r = await ask(lane.port, "news.example")
            assert [str(x.rdata) for x in r.rr] == [SITE_IP]
            assert all(x.ttl <= 30 for x in r.rr)
            r = await ask(lane.port, "cloaked.news.example")
            assert [str(x.rdata) for x in r.rr] == ["0.0.0.0"]

            engine.set_enabled("system", False)
            r = await ask(lane.port, "www.google-analytics.com")
            assert [str(x.rdata) for x in r.rr] == [SITE_IP]
            assert lane.stats.requests == 4 and lane.stats.blocked == 2  # AAAA not double-counted
        finally:
            for c in closers:
                c.close()
            dns_t.close()
    asyncio.run(run())


def test_dns_lane_in_crumbs_mode_passes_crumbs_answers_through():
    async def run():
        normal_t, _, normal_addr = await start_fake_dns()
        crumbs_t, _, crumbs_addr = await start_fake_dns(sinkhole={"ib.adnxs.com"})
        engine = Engine(lists(), upstream=Upstream([normal_addr], os_fallback=False),
                        crumbs=Upstream([crumbs_addr], os_fallback=False))
        lane = engine.add_lane(Lane("system", "S", "dns", free_port(socket.SOCK_DGRAM), enabled=True))
        closers = await start_dns(engine, lane, ["127.0.0.1"])
        try:
            r = await ask(lane.port, "ib.adnxs.com")
            assert [str(x.rdata) for x in r.rr] == ["0.0.0.0"]
            assert lane.stats.blocked == 1
            assert lane.stats.recent[-1]["company"] == "Microsoft (Xandr)"
        finally:
            for c in closers:
                c.close()
            normal_t.close()
            crumbs_t.close()
    asyncio.run(run())


# --- control API ----------------------------------------------------------------

def test_control_api_toggle_state_and_page_events():
    async def run():
        engine = Engine(lists())
        engine.add_lane(Lane("a", "A", "proxy", 1, enabled=False))
        ctl = ControlServer(engine, 0)
        status, _, body = await ctl.route("POST", "/api/lanes/a", b'{"enabled": true}', {}, None)
        assert status.startswith("200") and json.loads(body)["enabled"] is True
        status, _, _ = await ctl.route("POST", "/api/page-event",
                                       b'{"lane": "a", "auction": {"status": "won", "cpm": 1.5}}',
                                       {"user-agent": "test"}, ("127.0.0.1", 1))
        state = json.loads((await ctl.route("GET", "/api/state", b"", {}, None))[2])
        assert state["lanes"][0]["enabled"] is True
        assert state["page_events"][0]["auction"]["cpm"] == 1.5
        status, ctype, html = await ctl.route("GET", "/test", b"", {}, None)
        assert status.startswith("200") and b"pbjs" in html
        status, _, _ = await ctl.route("GET", "/static/../../README.md", b"", {}, None)
        assert status.startswith("404")
    asyncio.run(run())


# --- browser monitor ------------------------------------------------------------

def test_browser_outcomes_distinguish_crumbs_from_browser_blocking():
    from crumbs_demo.browser_monitor import LaneMonitor, outcome_for

    assert outcome_for("net::ERR_BLOCKED_BY_CLIENT", None) == "blocked by the browser itself"
    assert outcome_for("net::ERR_NAME_NOT_RESOLVED", None) == "DNS lookup failed"
    assert outcome_for("net::ERR_FAILED", "mixed-content") == "blocked by the browser itself"

    async def run():
        lane = Lane("b", "B", "proxy", 1, enabled=True)
        lane.stats.last_verdict.update({"www.google-analytics.com": "blocked", "slow.example": "allowed"})
        mon = LaneMonitor(lane, 0)
        for rid, url in (("1", "https://www.google-analytics.com/g/collect"), ("2", "https://slow.example/x")):
            await mon._handle({"method": "Network.requestWillBeSent", "sessionId": "s",
                               "params": {"requestId": rid, "type": "Fetch", "request": {"url": url}}})
            await mon._handle({"method": "Network.loadingFailed", "sessionId": "s",
                               "params": {"requestId": rid, "errorText": "net::ERR_TUNNEL_CONNECTION_FAILED"}})
        outcomes = [r["outcome"] for r in mon.requests]
        assert outcomes == ["blocked by Crumbs", "proxy could not connect"]
        assert mon.counts["crumbs"] == 1
    asyncio.run(run())


# --- Prebid summary -------------------------------------------------------------

def test_prebid_summary_combines_instances_and_tracks_failures():
    from crumbs_demo.prebid_reader import summarise

    assert summarise([]) == {"found": False}
    s = summarise([
        {"version": "v9.0.0", "ad_units": 2, "auctions": 1,
         "bids": [{"unit": "top", "bidder": "appnexus", "cpm": 1.2, "currency": "GBP"},
                  {"unit": "top", "bidder": "rubicon", "cpm": 2.0, "currency": "GBP"},
                  {"unit": "mpu", "bidder": "appnexus", "cpm": 0.8, "currency": "GBP"}],
         "won": [{"unit": "top", "bidder": "rubicon", "cpm": 2.0}],
         "requested": ["appnexus", "rubicon", "criteo"], "timed_out": ["criteo"], "errored": [], "no_bid": []},
        {"version": "v9.0.0", "ad_units": 1, "auctions": 1, "bids": [], "won": [],
         "requested": ["ix"], "timed_out": [], "errored": ["ix"], "no_bid": []},
    ])
    assert s["bidders_requested"] == ["appnexus", "criteo", "ix", "rubicon"]
    assert s["bidders_bid"] == ["appnexus", "rubicon"]
    assert s["top_bid_sum"] == 2.8          # best bid per slot: 2.0 + 0.8
    assert s["units_with_bids"] == 2 and s["ad_units"] == 3
    assert s["timed_out"] == ["criteo"] and s["errored"] == ["ix"]
    assert s["by_bidder"]["appnexus"] == {"bids": 2, "max_cpm": 1.2, "sum_cpm": 2.0}
    assert s["currency"] == "GBP" and s["won_sum"] == 2.0


def test_prebid_summary_counts_won_bids_missing_from_the_log():
    from crumbs_demo.prebid_reader import summarise

    s = summarise([{"ad_units": 0, "auctions": 2, "requested": ["ozone"], "timed_out": [], "errored": [],
                    "bids": [{"id": "x1", "auction": "a1", "unit": "mpu", "bidder": "ozone", "cpm": 1.1, "currency": "USD"}],
                    "won": [{"id": "x1", "auction": "a1", "unit": "mpu", "bidder": "ozone", "cpm": 1.1, "currency": "USD"},
                            {"id": "x2", "auction": "a2", "unit": "top", "bidder": "ozone", "cpm": 0.5, "currency": "USD"}]}])
    assert s["bids"] == 2 and s["won"] == 2          # x1 not double counted, x2 added
    assert s["units_with_bids"] == 2 and s["ad_units"] == 2
    assert s["top_bid_sum"] == 1.6
