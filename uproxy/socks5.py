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

class uSOCKS5(core.uProxy):
    """
    SOCKS5(h) Proxy server class for uProxy
    """

    async def _send_choice(self, cr,cw, REP):
        """
        REP is a single-byte reply
        """
        data = struct.pack('!BB', 5,REP)
        cw.write(data)
        await cw.drain()
        return data

    async def _send_reply(self, cr,cw, REP,ATYP=1,BND_ADDR='',BND_PORT=0):
        """
        REP:
        0x00: request granted
        0x01: general failure
        0x02: connection not allowed by ruleset
        0x03: network unreachable
        0x04: host unreachable
        0x05: connection refused by destination host
        0x06: TTL expired
        0x07: command not supported / protocol error
        0x08: address type not supported
        """
        assert ATYP!=4, "ipv6 unsupported"

        if ATYP==3:
            addrlen = len(BND_ADDR)
        else:
            BND_ADDR = socket.inet_pton(socket.AF_INET, BND_ADDR) if BND_ADDR else b'\0\0\0\0' # to 4 bytes
            addrlen = 4

        fmt = '!BBsB%dsH' % addrlen
        data = struct.pack(fmt, 5,REP,b'\0',ATYP,BND_ADDR,BND_PORT)
        cw.write(data)
        await cw.drain()
        return data

    async def _handshake(self, cr,cw):
        """
        SOCKS5(h) handshake
        """
        src_ip, src_port = core.ss_get_peername(cr)
        rr = rw = None

        try:
            buf = bytearray(self.bufsize if self.bufsize>257 else 512)
            mv = memoryview(buf)
            n = await cr.readinto(mv)

            # choose auth method
            assert mv[0]==5, "wrong ver"
            nmethods = mv[1]
            methods = mv[2:2+nmethods]
            if nmethods>2 and methods[2]==2:
                code = 2 # username:password auth
            elif methods[0]==0:
                code = 0 # no auth
            else:
                code = 255 # no acceptable method
            await self._send_choice(cr,cw, REP=code)

            # authentication
            assert code!=255, "no acceptable auth"
            if code==2:
                n = await cr.readinto(mv)
                assert mv[0]==1, "wrong auth ver"
                usrlen = mv[1]
                p = 2+usrlen
                usr = mv[2:p]
                pwlen = mv[p]
                p += 1
                pw = mv[p:p+pwlen]
                crens = str(usr+b':'+pw, 'ascii')
                is_auth = crens==self.auth
                await self._send_choice(cr,cw, REP=not is_auth) # 0 for success
                assert is_auth, "auth failed"

            # parse request
            n = await cr.readinto(mv)
            assert mv[0]==5 and mv[2]==0, "wrong ver"
            cmd = mv[1]
            addrtype = mv[3]
            dst_ip = dst_port = None
            if addrtype==1:
                dst_ip = socket.inet_ntop(socket.AF_INET, mv[4:8])
                dst_port = struct.unpack('!H', mv[8:10])[0]
            elif addrtype==3:
                addrlen = mv[4]
                p = 5+addrlen
                dst_ip = str(mv[5:p], 'ascii') # domain
                dst_port = struct.unpack('!H', mv[p:p+2])[0]
            if not dst_ip:
                await self._send_reply(cr,cw, REP=1)
                raise Exception("invalid addr")

            if cmd == 1:
                # CONNECT
                self._log(core.LOG_INFO, "CONNECT\t%s:%d\t==>\t%s:%d" % (src_ip, src_port, dst_ip, dst_port))
                rr, rw = await core._open_connection(dst_ip, dst_port, local_addr=self.bind)
                bnd_ip = self.ip
                bnd_port = 0 # TODO: until micropython implements a method to get ip and port from a socket
                await self._send_reply(cr,cw, REP=0, BND_ADDR=bnd_ip, BND_PORT=bnd_port)

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
                        await self._send_reply(cr,cw, REP=1)
                        raise Exception("no port")
                    self._log(core.LOG_DEBUG, "BIND\tlisten on\t\t<==\t%s:%d" % (self.ip, bnd_port))
                    await self._send_reply(cr,cw, REP=0, BND_ADDR=0, BND_PORT=bnd_port) # INADDR_ANY

                    await asyncio.wait_for(ready.wait(), timeout=self.timeout)
                    bnd_ip, bnd_port = core.ss_get_peername(rr) # set via `bind_accept()`
                    if bnd_ip != dst_ip:
                        await self._send_reply(cr,cw, REP=1)
                        raise Exception("ip mismatch")
                    self._log(core.LOG_INFO, "BIND\t%s:%d\t<==\t%s:%d" % (src_ip, src_port, bnd_ip, bnd_port))
                    await self._send_reply(cr,cw, REP=0, BND_ADDR=bnd_ip, BND_PORT=bnd_port)

                except asyncio.TimeoutError:
                    await core.ss_ensure_close(srv)
                except Exception as er:
                    await core.ss_ensure_close(srv)
                    raise er

            elif cmd == 3:
                await self._send_reply(cr,cw, REP=1)
                raise Exception("not implemented")

            else:
                await core.ss_ensure_close(cw)
                return None, None

        except Exception as err:
            self._log(core.LOG_INFO, "└─error, %s" % repr(err))
            await core.ss_ensure_close(cw)
            await core.ss_ensure_close(rw)
            return None, None

        return rr, rw
