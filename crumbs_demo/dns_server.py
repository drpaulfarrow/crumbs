"""The system DNS lane: a real DNS server (UDP and TCP) Windows can be pointed at."""

from __future__ import annotations

import asyncio
import logging
import struct

from dnslib import AAAA, A, QTYPE, RCODE, RR, DNSRecord

from .engine import Engine, Lane
from .upstream import is_sinkholed

log = logging.getLogger("crumbs.dns")

BLOCK_TTL = 10
MAX_TTL = 30  # keep answers short-lived so toggling takes effect quickly
RECORDED_QTYPES = {QTYPE.A}  # Windows asks A and AAAA per lookup; count each lookup once


class DnsHandler:
    def __init__(self, engine: Engine, lane: Lane):
        self.engine = engine
        self.lane = lane

    def _blocked_reply(self, request: DNSRecord) -> bytes:
        reply = request.reply()
        q = request.q
        if q.qtype == QTYPE.A:
            reply.add_answer(RR(q.qname, QTYPE.A, rdata=A("0.0.0.0"), ttl=BLOCK_TTL))
        elif q.qtype == QTYPE.AAAA:
            reply.add_answer(RR(q.qname, QTYPE.AAAA, rdata=AAAA("::"), ttl=BLOCK_TTL))
        else:
            reply.header.rcode = RCODE.NXDOMAIN
        return reply.pack()

    async def handle(self, data: bytes) -> bytes | None:
        try:
            request = DNSRecord.parse(data)
        except Exception:
            return None
        host = str(request.q.qname).rstrip(".")
        record = request.q.qtype in RECORDED_QTYPES
        if self.engine.uses_crumbs(self.lane):
            return await self._via_crumbs(request, data, host, record)
        decision = self.engine.decide(self.lane, host, record=False)
        if decision.blocked:
            if record:
                self.engine.record(self.lane, decision)
            return self._blocked_reply(request)
        try:
            raw = await self.engine.upstream.forward(data)
            response = DNSRecord.parse(raw)
        except Exception as e:
            log.warning("upstream failed for %s: %s", host, e)
            reply = request.reply()
            reply.header.rcode = RCODE.SERVFAIL
            return reply.pack()

        # CNAME cloaking: a first-party name that aliases to a tracker.
        if self.lane.enabled:
            for rr in response.rr:
                if rr.rtype == QTYPE.CNAME:
                    target = str(rr.rdata).rstrip(".")
                    cloaked = self.engine.decide(self.lane, target, record=False)
                    if cloaked.blocked:
                        if record:
                            cloaked.host = host
                            self.engine.record(self.lane, cloaked, note=f"CNAME cloak to {target}")
                        return self._blocked_reply(request)

        if record:
            self.engine.record(self.lane, decision)
        for rr in response.rr + response.auth + response.ar:
            rr.ttl = min(rr.ttl, MAX_TTL)
        return response.pack()


    async def _via_crumbs(self, request: DNSRecord, data: bytes, host: str, record: bool) -> bytes:
        """Crumbs on, real-Crumbs mode: Crumbs' resolver answers, we only watch."""
        try:
            response = DNSRecord.parse(await self.engine.crumbs.forward(data))
        except Exception as e:
            log.warning("Crumbs resolver failed for %s: %s", host, e)
            reply = request.reply()
            reply.header.rcode = RCODE.SERVFAIL
            return reply.pack()
        if record:
            self.engine.record(self.lane, self.engine.labelled(
                host, is_sinkholed(response), "Crumbs resolver"))
        for rr in response.rr + response.auth + response.ar:
            rr.ttl = min(rr.ttl, MAX_TTL)
        return response.pack()


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, handler: DnsHandler):
        self.handler = handler
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.ensure_future(self._respond(data, addr))

    async def _respond(self, data, addr):
        reply = await self.handler.handle(data)
        if reply and self.transport:
            self.transport.sendto(reply, addr)


async def _tcp_client(handler: DnsHandler, reader, writer):
    try:
        while True:
            header = await reader.readexactly(2)
            (length,) = struct.unpack("!H", header)
            reply = await handler.handle(await reader.readexactly(length))
            if reply is None:
                break
            writer.write(struct.pack("!H", len(reply)) + reply)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()


async def start_dns(engine: Engine, lane: Lane, hosts: list[str]) -> list:
    """Start UDP and TCP listeners on each host. Returns transports/servers to close."""
    handler = DnsHandler(engine, lane)
    loop = asyncio.get_running_loop()
    opened, errors = [], []
    for host in hosts:
        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpProtocol(handler), local_addr=(host, lane.port))
            opened.append(transport)
            server = await asyncio.start_server(
                lambda r, w: _tcp_client(handler, r, w), host, lane.port)
            opened.append(server)
        except OSError as e:
            errors.append(f"{host}:{lane.port} ({e.strerror or e})")
    lane.running = bool(opened)
    lane.error = "; ".join(errors) or None
    return opened
