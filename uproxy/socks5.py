# SOCKS4 proxy for uproxy module
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT

import struct
import socket
try:
    import uasyncio as asyncio
    from uasyncio.stream import Stream
except:
    import asyncio
    class Stream: pass

from . import core

class Datagram(Stream):
    ra = None # remote address
    la = None # local address

    # async
    def recvfrom(self, n=0):
        yield asyncio.core._io_queue.queue_read(self.s)
        r, a = self.s.recvfrom(n)
        self.ra = a
        return r, a

    def sendto(self, buf, addr=None):
        assert self.ra or addr
        if not self.ra:
            self.ra = addr
        if not addr:
            addr = self.ra
        return self.s.sendto(buf, addr)

def _create_endpoint(lhost=None, lport=None, rhost=None, rport=None):
    laddr = None if not lhost else socket.getaddrinfo(lhost, lport)[0][-1]
    raddr = None if not rhost else socket.getaddrinfo(rhost, rport)[0][-1]
    # assert laddr or raddr
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if laddr:
        s.bind(laddr)
    if raddr:
        s.connect(raddr)
    ss = Datagram(s)
    ss.ra = raddr
    ss.la = laddr
    yield asyncio.core._io_queue.queue_write(s)
    return ss, ss


REQ_GRANTED = 0
REQ_FAILURE = 1

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

    async def _relay_data(self, cr,cw, rr,rw):
        """
        Relay udp pkts between client and remote revolving `rr` endpoint
        """
        t = asyncio.current_task()
        mute = False

        async def wait_tcp(cr,cw, rr,rw):
            # monitor primary tcp connection
            nonlocal mute
            try:
                while True:
                    d = await cr.read(0)
                    if len(d)==0:
                        break
            except:
                pass
            mute = True
            await asyncio.sleep(1) # close
            await core.ss_ensure_close(cw)
            await core.ss_ensure_close(rw)

        async def relay_udp(cr,cw, rr,rw):
            nonlocal mute
            ca = ra = None
            src_ip, _ = core.ss_get_peername(cr)
            dst_ip = None
            try:
                while True:
                    # verify incoming udp pkt
                    buf, addr = await asyncio.wait_for(rr.recvfrom(self.bufsize), timeout=self.timeout)
                    ip, port = core.ss_addr_decode(addr)

                    if ip==src_ip:
                        # unwrap incoming client udp pkt and send it to remote
                        ca = addr

                        # parser pkt header
                        p = 0
                        mv = memoryview(buf)
                        if mv[0:2]!=b'\0\0':
                            continue # invalid pkt
                        frag = mv[2]
                        if frag!=0:
                            continue # TODO: add udp frag support
                        atyp = mv[3]
                        if atyp==1:
                            dst_ip = socket.inet_ntop(socket.AF_INET, mv[4:8])
                            dst_port = struct.unpack('!H', mv[8:10])[0]
                            p = 10
                        elif atyp==3:
                            addrlen = mv[4]
                            p = 5+addrlen
                            dst_ip = str(mv[5:p], 'ascii') # domain
                            dst_port = struct.unpack('!H', mv[p:p+2])[0]
                            p += 2
                        if not dst_ip or not dst_port:
                            continue # invalid dst addr

                        # unwrap and forward
                        data = mv[p:]
                        ra = socket.getaddrinfo(dst_ip, dst_port)[0][-1]
                        dst_ip, dst_port = core.ss_addr_decode(ra)
                        n = rw.sendto(data, ra)
                        assert n==len(data), 'sendto() failed'

                    elif ip==dst_ip:
                        # wrap incoming remote udp pkt and send it to client
                        buf = b'\0\0\0\x01\0\0\0\0\0\0'+buf
                        n = rw.sendto(buf, ca)
                        assert n==len(buf), 'sendto() failed'

                    else:
                        continue # drop pkt

            except asyncio.TimeoutError:
                pass
            except Exception as err:
                not mute and self._log(core.LOG_INFO, "└─error, %s" % repr(err), traceback=1)
            await core.ss_ensure_close(rw)
            await core.ss_ensure_close(cw)

        t_waittcp = asyncio.create_task(wait_tcp(cr,cw, rr,rw))
        t_waittcp.parent = t
        t_relayudp = asyncio.create_task(relay_udp(cr,cw, rr,rw))
        t_relayudp.parent = t
        await asyncio.gather(t_waittcp,t_relayudp, return_exceptions=False)
        await core.ss_ensure_close(rw)
        await core.ss_ensure_close(cw)
        return

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
            methods = [c for c in mv[2:2+nmethods]]
            code = 255 # no acceptable method
            if not self.auth and 0 in methods:
                code = 0 # no auth
            elif self.auth and 2 in methods:
                code = 2 # username:password auth
            await self._send_choice(cr,cw, REP=code)
            assert code!=255, "no acceptable auth"

            # authentication
            if code==2:
                n = await cr.readinto(mv)
                assert n!=0, "no reply"
                assert mv[0]==1, "wrong auth ver"
                usrlen = mv[1]
                p = 2+usrlen
                usr = mv[2:p]
                pwlen = mv[p]
                p += 1
                pw = mv[p:p+pwlen]
                crens = str(b'%s:%s' % (usr,pw), 'ascii')
                assert crens==self.auth, "auth failed"
                await self._send_choice(cr,cw, REP=REQ_GRANTED)

        except Exception as err:
            self._log(core.LOG_INFO, "└─error, %s" % repr(err))
            await self._send_choice(cr,cw, REP=REQ_FAILURE)
            await asyncio.sleep(0)
            await core.ss_ensure_close(cw)
            return None, None

        try:
            # parse request
            n = await cr.readinto(mv)
            assert n!=0, "no reply"
            assert mv[0]==5 and mv[2]==0, "wrong ver"
            cmd = mv[1]
            atyp = mv[3]
            dst_ip = dst_port = None
            if atyp==1:
                dst_ip = socket.inet_ntop(socket.AF_INET, mv[4:8])
                dst_port = struct.unpack('!H', mv[8:10])[0]
            elif atyp==3:
                addrlen = mv[4]
                p = 5+addrlen
                dst_ip = str(mv[5:p], 'ascii') # domain
                dst_port = struct.unpack('!H', mv[p:p+2])[0]
            else:
                raise Exception("invalid atyp")

            if cmd == 1:
                # CONNECT
                self._log(core.LOG_INFO, "CONNECT\t%s:%d\t==>\t%s:%d" % (src_ip, src_port, dst_ip, dst_port))
                rr, rw = await core._open_connection(dst_ip, dst_port, local_addr=self.bind)
                bnd_ip = self.ip
                bnd_port = 0 # TODO: needs micropython to implement a way to get ip and port from a socket
                await self._send_reply(cr,cw, REP=REQ_GRANTED, BND_ADDR=bnd_ip, BND_PORT=bnd_port)

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
                    # listen
                    bnd_port = core.get_free_port(proto=socket.SOCK_DGRAM)
                    srv = await core._start_server(bind_accept, self.ip, bnd_port, backlog=self.backlog) # get a random port
                    self._log(core.LOG_DEBUG, "BIND\tlisten on\t\t<==\t%s:%d" % (self.ip, bnd_port))
                    await self._send_reply(cr,cw, REP=REQ_GRANTED, BND_ADDR=0, BND_PORT=bnd_port) # INADDR_ANY

                    # wait for incoming connection
                    await asyncio.wait_for(ready.wait(), timeout=self.timeout)
                    bnd_ip, bnd_port = core.ss_get_peername(rr) # set via `bind_accept()`
                    assert bnd_ip==dst_ip, 'ip mismatch'
                    self._log(core.LOG_INFO, "BIND\t%s:%d\t<==\t%s:%d" % (src_ip, src_port, bnd_ip, bnd_port))
                    await self._send_reply(cr,cw, REP=REQ_GRANTED, BND_ADDR=bnd_ip, BND_PORT=bnd_port)

                except Exception as er:
                    await core.ss_ensure_close(srv)
                    raise er

            elif cmd == 3:
                # UDP_ASSOCIATE
                bnd_port = core.get_free_port(af=socket.AF_INET, proto=socket.SOCK_DGRAM)
                rr, rw =  await _create_endpoint(lhost=self.ip, lport=bnd_port) # get a random port
                self._log(core.LOG_INFO, "UDP ASSOCIATE\tstart at\t\t<==\t%s:%d" % (self.ip, bnd_port))
                await self._send_reply(cr,cw, REP=REQ_GRANTED, BND_ADDR=0, BND_PORT=bnd_port) # INADDR_ANY

            else:
                raise Exception("unknown cmd")
                return None, None

        except Exception as err:
            self._log(core.LOG_INFO, "└─error, %s" % repr(err))
            await self._send_reply(cr,cw, REP=REQ_FAILURE)
            await asyncio.sleep(0)
            await core.ss_ensure_close(cw)
            await core.ss_ensure_close(rw)
            return None, None

        return rr, rw

    async def _accept_conn(self, cr, cw):
        """
        asyncio version of `connection.accept()`
        Runs on a new task
        """
        rr = rw = 0
        self._conns += 1
        await asyncio.sleep(0)
        self._limit_conns()
        await asyncio.sleep(0)
        try:
            rr, rw = await self._handshake(cr,cw)
        except:
            await core.ss_ensure_close(cw)
            await core.ss_ensure_close(rw)
            rr = rw = 0
        self._conns -= 1
        await asyncio.sleep(0)
        self._limit_conns()
        await asyncio.sleep(0)

        if not rr:
            return

        try:
            if isinstance(rr, Datagram):
                await self._relay_data(cr,cr, rr,rw)
            else:
                await self._forward_data(cr,cw, rr,rw)
        except:
            await core.ss_ensure_close(cw)
            await core.ss_ensure_close(rw)

        self._log(core.LOG_DEBUG, "└─close")
