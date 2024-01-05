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

class uSOCKS4(core.uProxy):
    """
    SOCKS4(a) Proxy server class for uProxy
    """

    async def _send_reply(self, cr,cw ,REP,DSTPORT='',DSTIP=0):
        DSTIP = socket.inet_pton(socket.AF_INET, DSTIP) if DSTIP else b'\0\0\0\0' # to 4 bytes
        data = struct.pack('!BBH4s', 0,REP,DSTPORT,DSTIP)
        cw.write(data)
        await cw.drain()
        return data

    async def _handshake(self, cr,cw):
        """
        SOCKS4(a) handshake
        """
        src_ip, src_port = core.ss_get_peername(cr)
        rr = rw = None

        try:
            buf = bytearray(self.bufsize)
            mv = memoryview(buf)
            n = await cr.readinto(mv)
            mv[n] = 0 # NULL terminates

            # check signature
            ver = mv[0]
            if ver!=4:
                await self._send_reply(cr,cw, REP=91)
                raise Exception("wrong ver")

            # parse request
            cmd, dst_port = struct.unpack('!BH', mv[1:4])
            dst_ip = socket.inet_ntop(socket.AF_INET, mv[4:8])
            s = bytes(mv[8:n-1]).split(b'\0')
            userid = str(s[0], 'ascii')

            # parse SOCKS4a extension
            if dst_ip.startswith('0.0.0.') and len(s)>1:
                dst_ip = str(s[1], 'ascii')

            if cmd == 1:
                # CONNECT
                self._log(core.LOG_INFO, "CONNECT\t%s:%d\t==>\t%s:%d" % (src_ip, src_port, dst_ip, dst_port))
                rr, rw = await core._open_connection(dst_ip, dst_port, local_addr=self.bind)
                await self._send_reply(cr,cw, REP=90)

            elif cmd == 2:
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
                    # listen to a random port that is available
                    avail = False # port available
                    for i in range(1,3):
                        bnd_port = core.randrange(49152, 65535)
                        try:
                            srv = await core._start_server(bind_accept, self.ip, bnd_port, backlog=self.backlog) # get a random port
                        except:
                            await core.ss_ensure_close(srv)
                            await asyncio.sleep(0)
                            continue
                        avail = True
                        break
                    if not avail:
                        await self._send_reply(cr,cw, REP=91)
                        raise Exception("no port")
                    self._log(core.LOG_DEBUG, "BIND\tlisten on\t\t<==\t%s:%d" % (self.ip, bnd_port))
                    await self._send_reply(cr,cw, REP=90, DSTPORT=bnd_port, DSTIP=0) # INADDR_ANY

                    await asyncio.wait_for(ready.wait(), timeout=self.timeout)
                    bnd_ip, bnd_port = core.ss_get_peername(rr) # set via `bind_accept()`
                    if bnd_ip != dst_ip:
                        await self._send_reply(cr,cw, REP=91)
                        raise Exception("ip mismatch")
                    self._log(core.LOG_INFO, "BIND\t%s:%d\t<==\t%s:%d" % (src_ip, src_port, bnd_ip, bnd_port))
                    await self._send_reply(cr,cw, REP=90, DSTPORT=bnd_port, DSTIP=bnd_ip)

                except asyncio.TimeoutError:
                    await core.ss_ensure_close(srv)
                except Exception as er:
                    await core.ss_ensure_close(srv)
                    raise er

            else:
                await core.ss_ensure_close(cw)
                return None, None

        except Exception as err:
            self._log(core.LOG_INFO, "└─error, %s" % repr(err))
            await core.ss_ensure_close(cw)
            await core.ss_ensure_close(rw)
            return None, None

        return rr, rw
