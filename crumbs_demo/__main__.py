"""Command line: `python -m crumbs_demo [run|update-lists]`."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import webbrowser
from functools import partial

from .blocklist import Blocklists, download_lists
from .control import ControlServer, load_demo_config
from .dns_server import start_dns
from .engine import Engine, Lane
from .browser_monitor import LaneMonitor
from .launcher import launch_ab, window_bounds
from .system_dns import system_dns_state
from .proxy import LaneProxy
from .upstream import Upstream

log = logging.getLogger("crumbs")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crumbs_demo", description="Crumbs on/off A/B demo")
    sub = p.add_subparsers(dest="command")

    run = sub.add_parser("run", help="start the lanes, DNS server and control panel (default)")
    run.add_argument("--panel-port", type=int, default=5380)
    run.add_argument("--lane-a-port", type=int, default=8081)
    run.add_argument("--lane-b-port", type=int, default=8082)
    run.add_argument("--cdp-a-port", type=int, default=9231, help="DevTools port window A is watched on")
    run.add_argument("--cdp-b-port", type=int, default=9232, help="DevTools port window B is watched on")
    run.add_argument("--browser", choices=["edge", "chrome"], default=None,
                     help="browser for the A/B windows (default: 'browser' in demo_config.json, else edge)")
    run.add_argument("--dns-port", type=int, default=53)
    run.add_argument("--no-dns", action="store_true", help="don't start the system DNS lane")
    run.add_argument("--upstream", default="auto",
                     help="normal DNS: comma-separated IPs or a DoH URL (default: your original DNS, else 1.1.1.1)")
    run.add_argument("--crumbs-resolver", default=None,
                     help="real Crumbs DNS IPs or DoH URL (default: crumbs_resolver in demo_config.json). "
                          "'local' uses the bundled EasyPrivacy list instead")
    run.add_argument("--block-ads", action="store_true",
                     help="also block ad-serving domains (Crumbs itself targets trackers, not ads)")
    run.add_argument("--launch", action="store_true", help="open the A/B browser windows on start")
    run.add_argument("--page", choices=["site", "test"], default="site",
                     help="what the A/B windows open: real sites from demo_config.json, or the Prebid test page")
    run.add_argument("--no-open", action="store_true", help="don't open the control panel")
    run.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("update-lists", help="download EasyPrivacy and EasyList")
    check = sub.add_parser("check-crumbs", help="see how the Crumbs resolver answers from this network")
    check.add_argument("--crumbs-resolver", default=None)
    return p


def crumbs_spec(cli_value: str | None) -> str | None:
    spec = cli_value if cli_value is not None else load_demo_config().get("crumbs_resolver", "")
    return None if not spec or spec == "local" else spec


CHECK_DOMAINS = [
    ("control", "www.wikipedia.org"),
    ("control", "www.bbc.co.uk"),
    ("tracker", "www.google-analytics.com"),
    ("tracker", "connect.facebook.net"),
    ("tracker", "sb.scorecardresearch.com"),
    ("ad", "ib.adnxs.com"),
    ("ad", "securepubads.g.doubleclick.net"),
    ("malware test", "malware.testcategory.com"),
]


async def health_check(crumbs: Upstream, normal: Upstream) -> str | None:
    """None if Crumbs resolves ordinary sites; otherwise a warning for the panel."""
    from dnslib import DNSRecord
    from .upstream import is_sinkholed
    try:
        plain = DNSRecord.parse(await normal.forward(DNSRecord.question("www.wikipedia.org", "A").pack()))
        if is_sinkholed(plain):
            return "Normal DNS can't resolve www.wikipedia.org either: this network is blocking or rewriting DNS."
    except Exception as e:
        return f"Normal DNS ({normal.describe()}) did not answer ({e}). Check --upstream / the network."
    try:
        reply = DNSRecord.parse(await crumbs.forward(DNSRecord.question("www.wikipedia.org", "A").pack()))
    except Exception as e:
        return f"Crumbs resolver did not answer ({e}). 'Crumbs on' lanes will fail to load pages."
    if is_sinkholed(reply):
        return ("Crumbs resolver refused www.wikipedia.org from this network. It probably only serves "
                "your linked (home) IP address: everything would look blocked.")
    return None


async def check_crumbs(spec: str) -> int:
    from dnslib import QTYPE, RCODE, DNSRecord
    from .upstream import is_sinkholed
    crumbs = Upstream(spec, os_fallback=False)
    normal = Upstream("auto", os_fallback=False)
    print(f"Crumbs resolver: {crumbs.describe()}   normal DNS: {normal.describe()}\n")
    print(f"{'kind':<13}{'domain':<34}{'normal DNS':<22}{'Crumbs':<28}verdict")
    for kind, host in CHECK_DOMAINS:
        row = []
        for up in (normal, crumbs):
            try:
                r = DNSRecord.parse(await up.forward(DNSRecord.question(host, "A").pack()))
                ips = [str(rr.rdata) for rr in r.rr if rr.rtype == QTYPE.A]
                row.append((RCODE[r.header.rcode], ips[:1], is_sinkholed(r)))
            except Exception as e:
                row.append(("ERROR", [type(e).__name__], False))
        (n_code, n_ips, _), (c_code, c_ips, c_sink) = row
        verdict = "BLOCKED by Crumbs" if c_sink and n_ips else ("allowed" if c_ips else "?")
        print(f"{kind:<13}{host:<34}{n_code + ' ' + ','.join(n_ips):<22}{c_code + ' ' + ','.join(c_ips):<28}{verdict}")
    warning = await health_check(crumbs, normal)
    print("\n" + (f"WARNING: {warning}" if warning else "Crumbs resolver is serving this network."))
    return 1 if warning else 0


def ab_urls(panel_port: int, page: str) -> list[str]:
    if page == "test":
        return [f"http://127.0.0.1:{panel_port}/test?lane={{lane}}"]
    return load_demo_config().get("ab_sites", ["https://www.theguardian.com/"])


async def serve(args) -> None:
    lists = Blocklists.load()
    upstream = Upstream(args.upstream)
    spec = crumbs_spec(args.crumbs_resolver)
    crumbs = Upstream(spec, os_fallback=False) if spec else None
    engine = Engine(lists, upstream=upstream, crumbs=crumbs, block_ads=args.block_ads)
    if crumbs:
        engine.crumbs_warning = await health_check(crumbs, upstream)

    lane_a = engine.add_lane(Lane("a", "Window A (left)", "proxy", args.lane_a_port, enabled=False))
    lane_b = engine.add_lane(Lane("b", "Window B (right)", "proxy", args.lane_b_port, enabled=True))
    closers = []
    for lane in (lane_a, lane_b):
        proxy = LaneProxy(engine, lane)
        await proxy.start()
        if proxy.server:
            closers.append(proxy.server)
    if not args.no_dns:
        system = engine.add_lane(Lane("system", "Whole PC (system DNS)", "dns", args.dns_port, enabled=True))
        closers += await start_dns(engine, system, ["127.0.0.1", "::1"])

    monitors = {}
    for lane, cdp_port in ((lane_a, args.cdp_a_port), (lane_b, args.cdp_b_port)):
        lane.monitor = monitors[lane.name] = LaneMonitor(lane, cdp_port)
        lane.monitor.start()
    browser = args.browser or load_demo_config().get("browser", "edge")

    def launcher(page: str = args.page):
        # Windows start blank; each monitor opens the pages once it's attached,
        # so the live request view sees the very first request.
        urls = ab_urls(args.panel_port, page)
        started = launch_ab({"a": (args.lane_a_port, args.cdp_a_port),
                             "b": (args.lane_b_port, args.cdp_b_port)}, [], prefer=browser)
        for i, name in enumerate(started):
            monitors[name].open_urls([u.replace("{lane}", name) for u in urls], window_bounds(i, len(started)))
        return started

    control = ControlServer(engine, args.panel_port, launcher=launcher)
    closers.append(await control.start())
    panel = f"http://127.0.0.1:{args.panel_port}/"

    print(f"\n  Crumbs demo running. Control panel: {panel}")
    print(f"  Prebid test page:          http://127.0.0.1:{args.panel_port}/test")
    print(f"  From the Android emulator: http://10.0.2.2:{args.panel_port}/test?lane=emulator")
    print(f"  Lists: {len(lists.trackers)} tracker / {len(lists.ads)} ad domains ({lists.sources['trackers']})")
    print(f"  Normal DNS upstream: {upstream.describe()}")
    print(f"  Crumbs on means: {'Crumbs resolver ' + crumbs.describe() if crumbs else 'local EasyPrivacy list'}")
    for lane in engine.lanes.values():
        status = "listening" if lane.running else f"NOT RUNNING: {lane.error}"
        print(f"  Lane {lane.name:<6} port {lane.port:<5} {status}")
    if engine.crumbs_warning:
        print(f"  WARNING: {engine.crumbs_warning}")
    if "system" in engine.lanes and not system_dns_state()["switched"]:
        print("  Whole PC lane: Windows isn't using it yet (panel button, or scripts\\windows\\system-dns-on.ps1).")
    print("  Ctrl+C to stop.\n")

    if not args.no_open:
        webbrowser.open(panel)
    if args.launch:
        try:
            launcher()
        except FileNotFoundError as e:
            print(f"  Could not launch browsers: {e}")
    try:
        await asyncio.Event().wait()
    finally:
        for c in closers:
            c.close()
        if system_dns_state()["switched"]:
            print("\n  WARNING: Windows is still pointed at this demo's DNS server, so name lookups will fail.\n"
                  "  Run scripts\\windows\\system-dns-off.ps1 as administrator to restore your DNS.\n")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]
    args = build_parser().parse_args(argv)
    if args.command == "check-crumbs":
        spec = crumbs_spec(args.crumbs_resolver)
        if not spec:
            print("No Crumbs resolver configured (crumbs_resolver in demo_config.json).")
            return 2
        return asyncio.run(check_crumbs(spec))
    if args.command == "update-lists":
        counts = download_lists()
        print(json.dumps({"domain_rules": counts}, indent=2))
        return 0
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
