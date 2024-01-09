# SOCKS4 proxy for uproxy module
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT

import struct
import socket
try:
    import uasyncio as asyncio
except:
    import asyncio
from . import core

REQ_GRANTED = 90
REQ_REJECTED = 91

class uSOCKS4(core.uProxy):
    """
    SOCKS4(a) Proxy server class for uProxy
    """

    async def _send_reply(self, cr,cw ,REP,DSTIP='',DSTPORT=0):
        DSTIP = socket.inet_pton(socket.AF_INET, DSTIP) if DSTIP else b'\0\0\0\0' # to 4 bytes
        data = struct.pack('!BBH4s', 0,REP,DSTPORT,DSTIP)
        cw.write(data)
        await cw.drain()
        return data

    async def _handshake(self, cr,cw):
        src_ip, src_port = core.ss_get_peername(cr)
        rr = rw = None

        try:
            buf = bytearray(self.bufsize)
            mv = memoryview(buf)
            n = await cr.readinto(mv)

            # parse request
            assert mv[0]==4, "wrong ver"
            cmd, dst_port = struct.unpack('!BH', mv[1:4])
            dst_ip = socket.inet_ntop(socket.AF_INET, mv[4:8])
            s = bytes(mv[8:n-1]).split(b'\0')
            if self.auth:
                userid = str(s[0], 'ascii')
                assert self.auth==userid, "auth failed %s:%d" % (src_ip, src_port)

            # SOCKS4a extension
            if dst_ip.startswith('0.0.0.') and len(s)>1:
                dst_ip = str(s[1], 'ascii')

            if self.upstream_ip:
                self._log(core.LOG_INFO, "FORWARD\t%s:%d\t==>\t%s:%d" % (src_ip, src_port, self.upstream_ip, self.upstream_port))
                rr, rw = await core._open_connection(self.upstream_ip, self.upstream_port, local_addr=self.bind)
                rw.write(mv[:n])
                await rw.drain()
                return rr, rw

            elif cmd==1:
                # CONNECT
                self._log(core.LOG_INFO, "CONNECT\t%s:%d\t==>\t%s:%d" % (src_ip, src_port, dst_ip, dst_port))
                rr, rw = await core._open_connection(dst_ip, dst_port, local_addr=self.bind)
                await self._send_reply(cr,cw, REP=REQ_GRANTED)

            elif cmd==2:
                # BIND
                srv = None
                ready = asyncio.Event()
                async def bind_accept(br,bw):
                    nonlocal rr, rw
                    rr = br
                    rw = bw
                    ready.set()
                    await core.ss_ensure_close(srv)

                try:
                    # listen to a random port
                    bnd_port = core.get_free_port(proto=socket.SOCK_STREAM)
                    srv = await core._start_server(bind_accept, self.ip, bnd_port, backlog=self.backlog)
                    self._log(core.LOG_DEBUG, "BIND\tlisten on\t\t<==\t%s:%d" % (self.ip, bnd_port))
                    await self._send_reply(cr,cw, REP=REQ_GRANTED, DSTPORT=bnd_port, DSTIP=0) # INADDR_ANY

                    await asyncio.wait_for(ready.wait(), timeout=self.timeout)
                    bnd_ip, bnd_port = core.ss_get_peername(rr) # set via `bind_accept()`
                    assert bnd_ip==dst_ip, "ip mismatch"
                    self._log(core.LOG_INFO, "BIND\t%s:%d\t<==\t%s:%d" % (src_ip, src_port, bnd_ip, bnd_port))
                    await self._send_reply(cr,cw, REP=REQ_GRANTED, DSTPORT=bnd_port, DSTIP=bnd_ip)

                except Exception as er:
                    await core.ss_ensure_close(srv)
                    raise er

            else:
                raise Exception("unknown cmd")
                return None, None

        except Exception as err:
            if not isinstance(err, asyncio.TimeoutError):
                self._log(core.LOG_INFO, "└─error, %s" % repr(err))
            await self._send_reply(cr,cw, REP=REQ_REJECTED)
            await asyncio.sleep(0)
            await core.ss_ensure_close(cw)
            await core.ss_ensure_close(rw)
            return None, None

        return rr, rw
