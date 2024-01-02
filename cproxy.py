#!/usr/bin/env python3
# A CPython wrapper for uProxy
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT
#
# > CPython only!
# > For MicroPython-compatible uProxy, refer to `uproxy.py`
#
import asyncio
import argparse
import uproxy

async def readinto(self, buf):
    """
    Polyfil for MicroPython's `asyncio.StreamWriter.readinto()`
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
uproxy.ss_get_peername = ss_get_peername

async def _open_connection(host, port, ssl=None, server_hostname=None, local_addr=None):
    local_addr = (local_addr, 0) if local_addr else None
    return await asyncio.open_connection(host=host, port=port, ssl=ssl, server_hostname=server_hostname, local_addr=local_addr)
uproxy._open_connection = _open_connection

async def _start_server(callback, host, port, backlog=100, ssl=None):
    server = await asyncio.start_server(client_connected_cb=callback, host=host, port=port, backlog=backlog, ssl=ssl)
    server.s = server._sockets[0]
    return server
uproxy._start_server = _start_server

def b64(text, enc=True):
    from base64 import b64encode, b64decode
    if enc:
        return b64encode(text.encode("ascii"))
    else:
        return b64decode(text.encode("ascii"))
uproxy.b64 = b64



class uProxy(uproxy.uProxy):
    """
    CPython compatible class
    """

    def _limit_conns(self):
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
                self._log(uproxy.LOG_INFO, "├─pipe disconnect, %s" % repr(err))
            await uproxy.ss_ensure_close(w)

        task_c2r = asyncio.create_task(io_copy(cr, rw))
        task_r2c = asyncio.create_task(io_copy(rr, cw))
        await asyncio.gather(task_c2r, task_r2c, return_exceptions=False)



if __name__== "__main__":
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
    parser.add_argument('--auth', help="a username:password pair for server authentication [%(default)s]", default=None, type=str)
    args = parser.parse_args()

    proxy = uProxy(ip=args.ip, port=args.port, bind=args.bind, \
                bufsize=args.bufsize, maxconns=args.maxconns, \
                backlog=args.backlog, timeout=args.timeout, \
                loglevel=args.loglevel, auth=args.auth)
    asyncio.run(proxy.run())

    print("done")
