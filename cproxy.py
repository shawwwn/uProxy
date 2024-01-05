#!/usr/bin/env python3
# A CPython wrapper for uProxy
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT
#
# > CPython only!
# > For MicroPython-compatible uProxy, refer to `uproxy.py`
#
import asyncio
import time
import uproxy
from uproxy.core import VERSION, LOG_NONE, LOG_INFO, LOG_DEBUG

old_import = __import__
def new_import(name, globals=None, locals=None, fromlist=(), level=0):
    pass

def ticks_diff(ticks1, ticks2):
    """
    Micropython Polyfil
    """
    return ticks1 - ticks2
time.ticks_diff = ticks_diff

def ticks_ms():
    """
    Micropython Polyfil
    """
    return int(time.time_ns()/1000)
time.ticks_ms = ticks_ms

async def readinto(self, buf):
    """
    Micropython Polyfil
    """
    l = len(buf)
    b = await self.read(l)
    lb = len(b)
    buf[0:lb] = b
    # buf[lb:lb+1] = b'\0'
    return len(b)
asyncio.StreamReader.readinto = readinto

def ss_get_peername(ss):
    return ss._transport.get_extra_info('peername')
uproxy.core.ss_get_peername = ss_get_peername

async def _open_connection(host, port, ssl=None, server_hostname=None, local_addr=None):
    local_addr = (local_addr, 0) if local_addr else None
    return await asyncio.open_connection(host=host, port=port, ssl=ssl, server_hostname=server_hostname, local_addr=local_addr)
uproxy.core._open_connection = _open_connection

async def _start_server(callback, host, port, backlog=100, ssl=None):
    server = await asyncio.start_server(client_connected_cb=callback, host=host, port=port, backlog=backlog, ssl=ssl)
    server.s = server._sockets[0]
    return server
uproxy.core._start_server = _start_server

def b64(text, enc=True):
    from base64 import b64encode, b64decode
    if enc:
        return b64encode(text.encode("ascii"))
    else:
        return b64decode(text.encode("ascii"))
uproxy.core.b64 = b64

def limit_conns(self):
    if not self.maxconns or self.maxconns<=0:
        return
    elif self._conns>=self.maxconns and self._polling:
        self._server._loop._selector._selector.unregister(self._server.s.fileno())
        self._log(uproxy.LOG_DEBUG, "polling disabled")
        self._polling = False
    elif self._conns<self.maxconns and not self._polling:
        self._server._loop._selector._selector.register(self._server.s.fileno())
        self._log(uproxy.LOG_DEBUG, "polling enabled")
        self._polling = True



#
# Attach global attributes
#
if hasattr(uproxy, 'uHTTP'):
    class uHTTP(uproxy.uHTTP):
        """
        CPython compatible uHTTP
        """

        _limit_conns = limit_conns

        async def _forward_data(self, cr,cw, rr,rw):
            """
            This function is much faster than the default
            method but will consume twice the memory.
            Compatible with MicroPython.
            """
            async def io_copy(r, w):
                """
                Forward data using a go-style coroutine
                """
                buf = bytearray(self.bufsize)
                mv = memoryview(buf)
                try:
                    while True:
                        n = await asyncio.wait_for(r.readinto(mv), timeout=self.timeout)
                        if n<=0:
                            break
                        w.write(mv[:n])
                        await w.drain()
                except Exception as err:
                    if not isinstance(err, asyncio.TimeoutError):
                        self._log(uproxy.LOG_INFO, "└─pipe disconnect, %s" % repr(err), traceback=1)
                await uproxy.ss_ensure_close(w)
                self._log(uproxy.LOG_DEBUG, "└─pipe close", traceback=1)

            t = asyncio.current_task()
            task_c2r = asyncio.create_task(io_copy(cr, rw))
            task_c2r._parent = t
            task_r2c = asyncio.create_task(io_copy(rr, cw))
            task_r2c._parent = t
            await asyncio.gather(task_c2r, task_r2c, return_exceptions=False)

    # add to global()
    globals()['uHTTP'] = uHTTP

if hasattr(uproxy, 'uSOCKS4'):
    class uSOCKS4(uproxy.uSOCKS4):
        """
        CPython compatible uSOCKS4
        """

        _limit_conns = limit_conns

        async def _forward_data(self, cr,cw, rr,rw):
            """
            This function is much faster than the default
            method but will consume twice the memory.
            Compatible with MicroPython.
            """
            async def io_copy(r, w):
                """
                Forward data using a go-style coroutine
                """
                buf = bytearray(self.bufsize)
                mv = memoryview(buf)
                try:
                    while True:
                        n = await asyncio.wait_for(r.readinto(mv), timeout=self.timeout)
                        if n<=0:
                            break
                        w.write(mv[:n])
                        await w.drain()
                except Exception as err:
                    if not isinstance(err, asyncio.TimeoutError):
                        self._log(uproxy.LOG_INFO, "└─pipe disconnect, %s" % repr(err), traceback=1)
                await uproxy.ss_ensure_close(w)
                self._log(uproxy.LOG_DEBUG, "└─pipe close", traceback=1)

            t = asyncio.current_task()
            task_c2r = asyncio.create_task(io_copy(cr, rw))
            task_c2r._parent = t
            task_r2c = asyncio.create_task(io_copy(rr, cw))
            task_r2c._parent = t
            await asyncio.gather(task_c2r, task_r2c, return_exceptions=False)

    # add to global()
    globals()['uHTTP'] = uHTTP



if __name__== "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--version', action='version', version='uProxy %0.1f' % uproxy.VERSION)
    parser.add_argument('--ip', help="server ip [%(default)s]", default='0.0.0.0', type=str)
    parser.add_argument('--port', help="server port [%(default)s]", default=8765, type=int)
    parser.add_argument('--bind', help="ip address for outgoing connections to bind to [%(default)s]", default=None, type=str)
    parser.add_argument('--bufsize', help="buffer size of each connection, in bytes [%(default)s]", default=8192, type=int)
    parser.add_argument('--maxconns', help="max number of accepted connections server can handle, 0 to disable [%(default)s]", metavar='N', default=0, type=int)
    parser.add_argument('--backlog', help="max number of unaccepted connections waiting to be processed [%(default)s]", metavar='M', default=100, type=int)
    parser.add_argument('--timeout', help="connection timeout, in seconds [%(default)s]", default=30, type=int)
    parser.add_argument('--loglevel', help="log level (0-quiet, 1-info, 2-debug) [%(default)s]", default=1, type=int)
    parser.add_argument('--auth', help="an username:password pair for server authentication [%(default)s]", default=None, type=str)
    parser.add_argument('--upstream', help="an ip:port pair to connect to as an upstream http proxy [%(default)s]", default=None, type=str)
    args = parser.parse_args()

    proxy = uHTTP(ip=args.ip, port=args.port, bind=args.bind, \
                bufsize=args.bufsize, maxconns=args.maxconns, \
                backlog=args.backlog, timeout=args.timeout, \
                loglevel=args.loglevel, auth=args.auth, \
                upstream=args.upstream)
    asyncio.run(proxy.run())

    print("done")
