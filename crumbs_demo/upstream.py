"""Talking to real DNS servers: the normal ones, and optionally Crumbs' own resolver.

An upstream spec is a comma-separated list of plain DNS server IPs
("1.1.1.1,8.8.8.8") or a single DNS-over-HTTPS URL ("https://.../dns-query").
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
import urllib.request
from dataclasses import dataclass

from dnslib import QTYPE, RCODE, DNSRecord

from .blocklist import CACHE_DIR

DEFAULT_UPSTREAMS = ["1.1.1.1", "8.8.8.8"]
ORIGINAL_DNS_FILE = CACHE_DIR / "original-dns.json"
SINKHOLE_IPS = {"0.0.0.0", "127.0.0.1", "::", "::1"}


def resolve_upstreams(spec: str) -> list[str]:
    """'auto' means: the DNS servers Windows used before system-dns-on.ps1, else public ones."""
    if spec != "auto":
        return [s.strip() for s in spec.split(",") if s.strip()]
    try:
        saved = json.loads(ORIGINAL_DNS_FILE.read_text(encoding="utf-8-sig"))
        servers = [s for a in saved.get("adapters", []) for s in a.get("servers", [])]
        servers = [s for s in servers if not ipaddress.ip_address(split_server(s)[0]).is_loopback]
        if servers:
            return list(dict.fromkeys(servers))
    except (OSError, ValueError):
        pass
    return list(DEFAULT_UPSTREAMS)


def split_server(server: str) -> tuple[str, int]:
    """'1.1.1.1' or '127.0.0.1:5353' (IPv6 addresses take no port)."""
    if server.count(":") == 1:
        host, port = server.split(":")
        return host, int(port)
    return server, 53


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def is_sinkholed(response: DNSRecord) -> bool:
    """How a filtering resolver says "blocked": REFUSED/NXDOMAIN, or a 0.0.0.0-style answer."""
    if response.header.rcode in (RCODE.REFUSED, RCODE.NXDOMAIN):
        return True
    addresses = [str(rr.rdata) for rr in response.rr if rr.rtype in (QTYPE.A, QTYPE.AAAA)]
    return bool(addresses) and all(a in SINKHOLE_IPS for a in addresses)


@dataclass
class Lookup:
    ips: list[str]
    cnames: list[str]
    sinkholed: bool


class _Exchange(asyncio.DatagramProtocol):
    def __init__(self, payload: bytes):
        self.payload = payload
        self.future: asyncio.Future = asyncio.get_running_loop().create_future()

    def connection_made(self, transport):
        transport.sendto(self.payload)

    def datagram_received(self, data, addr):
        if not self.future.done():
            self.future.set_result(data)

    def error_received(self, exc):
        if not self.future.done():
            self.future.set_exception(exc)


class Upstream:
    def __init__(self, spec: str | list[str], timeout: float = 2.5, os_fallback: bool = True):
        servers = spec if isinstance(spec, list) else resolve_upstreams(spec)
        self.doh_url = servers[0] if servers and servers[0].startswith("https://") else None
        self.servers = [] if self.doh_url else servers
        self.timeout = timeout
        self.os_fallback = os_fallback
        self._cache: dict[str, tuple[float, Lookup]] = {}

    def describe(self) -> str:
        return self.doh_url or ", ".join(self.servers)

    async def forward(self, packet: bytes) -> bytes:
        """Send a raw DNS query, return the raw answer."""
        if self.doh_url:
            return await asyncio.get_running_loop().run_in_executor(None, self._doh, packet)
        loop = asyncio.get_running_loop()
        last_error: Exception | None = None
        for server in self.servers:
            transport = None
            try:
                transport, proto = await loop.create_datagram_endpoint(
                    lambda: _Exchange(packet), remote_addr=split_server(server))
                return await asyncio.wait_for(proto.future, self.timeout)
            except (OSError, asyncio.TimeoutError) as e:
                last_error = e
            finally:
                if transport:
                    transport.close()
        raise ConnectionError(f"no upstream DNS answered: {last_error!r}")

    def _doh(self, packet: bytes) -> bytes:
        req = urllib.request.Request(self.doh_url, data=packet, method="POST", headers={
            "Content-Type": "application/dns-message",
            "Accept": "application/dns-message",
        })
        with urllib.request.urlopen(req, timeout=self.timeout * 2) as resp:
            return resp.read()

    async def lookup(self, host: str) -> Lookup:
        """A-record lookup with a small TTL cache."""
        if is_ip(host):
            return Lookup([host.strip("[]")], [], False)
        now = time.monotonic()
        hit = self._cache.get(host)
        if hit and hit[0] > now:
            return hit[1]
        result, ttl = Lookup([], [], False), 60
        try:
            reply = DNSRecord.parse(await self.forward(DNSRecord.question(host, "A").pack()))
            a_records = [rr for rr in reply.rr if rr.rtype == QTYPE.A]
            result = Lookup(
                ips=[str(rr.rdata) for rr in a_records],
                cnames=[str(rr.rdata).rstrip(".") for rr in reply.rr if rr.rtype == QTYPE.CNAME],
                sinkholed=is_sinkholed(reply),
            )
            if a_records:
                ttl = max(5, min(rr.ttl for rr in a_records))
        except Exception:
            pass
        if not result.ips and not result.sinkholed and self.os_fallback:
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(
                    host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
                result.ips = list(dict.fromkeys(info[4][0] for info in infos))
            except OSError:
                pass
        if result.ips or result.sinkholed:
            self._cache[host] = (now + ttl, result)
        return result
