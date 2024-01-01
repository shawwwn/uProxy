#!/usr/bin/env micropython
# uProxy - an minimal, memory-efficient HTTP/HTTPS proxy server made for MicroPython
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT
#
# > MicroPython only!
# > For CPython-compatible uProxy, refer to `cproxy.py`
#
import select
try:
    import uasyncio as asyncio
except:
    import asyncio

VERSION = 1.0
LOG_NONE = 0
LOG_INFO = 1
LOG_DEBUG = 2

def _open_connection(host, port, ssl=None, server_hostname=None, local_addr=None):
    """
    Adapted from `uasyncio.open_connection()`
    - Adds `local_addr` parameter
    TODO: deprecate this once micropython adds ip binding feature
    """
    from errno import EINPROGRESS
    import socket

    ai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]  # TODO this is blocking!
    s = socket.socket(ai[0], ai[1], ai[2])
    local_addr and s.bind(socket.getaddrinfo(local_addr, 0, socket.AF_INET, socket.SOCK_STREAM)[0][-1])
    s.setblocking(False)
    try:
        s.connect(ai[-1])
    except OSError as er:
        if er.errno != EINPROGRESS:
            raise er
    # wrap with SSL, if requested
    if ssl:
        if ssl is True:
            import ssl as _ssl

            ssl = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        if not server_hostname:
            server_hostname = host
        s = ssl.wrap_socket(s, server_hostname=server_hostname, do_handshake_on_connect=False)
        s.setblocking(False)
    # ss = asyncio.Stream(s)
    ss = asyncio.StreamWriter(s)
    yield asyncio.core._io_queue.queue_write(s)
    return ss, ss

async def _start_server(cb, host, port, backlog=100, ssl=None):
    """
    Adapted from `uasyncio.start_server()`
    - Attach socket object to `Server' class
    """
    import socket

    # Create and bind server socket.
    host = socket.getaddrinfo(host, port)[0]  # TODO this is blocking!
    s = socket.socket()
    s.setblocking(False)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(host[-1])
    s.listen(backlog)

    # Create and return server object and task.
    try:
        from uasyncio.stream import Server
    except:
        from asyncio.stream import Server
    srv = Server()
    srv.s = s
    srv.task = asyncio.core.create_task(srv._serve(s, cb, ssl))
    try:
        # Ensure that the _serve task has been scheduled so that it gets to
        # handle cancellation.
        await asyncio.core.sleep_ms(0)
    except asyncio.core.CancelledError as er:
        # If the parent task is cancelled during this first sleep, then
        # we will leak the task and it will sit waiting for the socket, so
        # cancel it.
        srv.task.cancel()
        raise er
    return srv



def parse_http_header(line):
    """
    Parse first line of incoming HTTP request
    """
    method, url, proto = line.split(b' ') # `proto` ends with b'\r\n'

    # remove 'http://' prefix
    i = url.find(b'://')
    if i!=-1:
        url = url[i+3:]

    # seperate path from url
    i = url.find(b'/')
    domain = url[:i] if i!=-1 else url
    path = url[i:] if i!=-1 else b'/'

    # seperate port from domain
    i = domain.find(b':')
    port = int(domain[i+1:]) if i!=-1 else 80
    domain = domain[:i] if i!=-1 else domain

    return method, domain, port, path, proto

async def send_http_response(ss, code, desc="", headers=[], body=None):
    """
    send HTTP response
    """
    cnt = 0
    try:
        l = b'HTTP/1.1 %d %s\r\n' % (code, desc)
        cnt += len(l)
        ss.write(l)
        for h in headers:
            ss.write(h+b'\r\n')
            cnt += len(h)+2
        ss.write(b'\r\n')
        cnt += 2
        await ss.drain()
    except Exception as err:
        await ss_ensure_close(ss)
        raise err
    return cnt

def ss_get_peername(ss):
    """
    Polyfill of `socket.getpeername()`
    @return: (ip, port)
    """
    import struct
    mv = memoryview(ss.get_extra_info('peername'))
    _, port, a, b, c, d = struct.unpack('!HHBBBB', mv[0:8])
    ip = '%u.%u.%u.%u' % (a, b, c, d)
    return ip, port

async def ss_ensure_close(ss):
    """
    Ensure asyncio Stream is closed, ignore any error
    """
    if not ss:
        return
    try:
        ss.close()
        await ss.wait_closed()
    except:
        pass



class uProxy:
    """
    Proxy Server
    """

    def __init__(self, ip='0.0.0.0', port=8765, bind=None, \
                bufsize=8192, maxconns=0, backlog=100, timeout=30, \
                ssl=None, loglevel=LOG_INFO, acl_callback=None):
        self.ip = ip
        self.port = port
        self.bind = bind
        self.bufsize = bufsize
        self.maxconns = maxconns
        self.backlog = backlog
        self.ssl = None                   # SSLContext
        self.loglevel = loglevel          # 0-silent, 1-normal, 2-debug
        self.timeout = timeout            # seconds
        self._server = None
        self.acl_callback = acl_callback
        self._conns = 0                   # current connection count
        self._polling = True              # server socket polling availability

    async def run(self):
        self._server = await _start_server(self._accept_conn, self.ip, self.port, backlog=self.backlog, ssl=self.ssl)
        self.loglevel>=LOG_INFO and print("Listening on %s:%d" % (self.ip, self.port))
        await self._server.wait_closed()

    def _log(self, lvl, msg):
        self.loglevel>=lvl and print(msg)

    def _limit_conns(self):
        """
        Temporarily disable socket polling if number of concurrent connections
        exceed a certain limit, so that server's listening socket will no longer
        accept new connections.
        Doing so will generate some connection loss errors, but nothing too
        serious.
        """
        return
        if not self.maxconns or self.maxconns<=0:
            return
        elif self._conns>=self.maxconns and self._polling:
            asyncio.core._io_queue.poller.unregister(self._server.s)
            self._log(LOG_DEBUG, "polling disabled")
            self._polling = False
        elif self._conns<self.maxconns and not self._polling:
            asyncio.core._io_queue.poller.register(self._server.s)
            self._log(LOG_DEBUG, "polling enabled")
            self._polling = True

    async def _accept_conn(self, cr, cw):
        """
        Non-blocking version of `connection.accept()`
        Runs on a new task
        @cr: stream reader for client socket
        @cw: stream writer for client socket
        """
        bytecnt = 0
        self._conns += 1
        self._limit_conns()

        src_ip, src_port = ss_get_peername(cr)

        # parse proxy header
        try:
            header = await cr.readline()
            if not header:
                raise
            bytecnt += len(header)
        except Exception as err:
            self._log(LOG_INFO, "  error, %s" % repr(err))
            await ss_ensure_close(cw)
            return
        method, dst_domain, dst_port, path, proto = parse_http_header(header)
        dst_ip = dst_domain.decode()

        # attach info to `Task` instance
        task = asyncio.current_task()
        task.src_ip = src_ip                # str
        task.src_port = src_port            # int
        task.dst_ip = dst_ip                # placeholder, not a real ip
        task.dst_domain = dst_domain        # bytes
        task.dst_port = dst_port            # int
        task.task_id = hex(id(task))        # str
        task.method = method                # bytes
        task.path = path                    # str
        task.proto = proto                  # str, ends with '\r\n'

        # access control
        # tip: task object can be accessed inside acl function
        if self.acl_callback and not self.acl_callback(src_ip, src_port, dst_ip, dst_port):
            await ss_ensure_close(cw)
            self._log(LOG_INFO, "BLOCK %s:%d --> %s:%d" % (src_ip, src_port, dst_ip, dst_port))
            return
        else:
            self._log(LOG_INFO, "%s\t%s:%d\t==>\t%s:%d" % (task.method.decode(), src_ip, src_port, dst_ip, dst_port))

        # serve command
        if method==b'CONNECT':
            bytecnt += await self._CONNECT(cr, cw)
        else:
            bytecnt += await self._CMD(cr, cw)
        self._log(LOG_DEBUG, "  close, %s bytes transfered" % bytecnt)

        self._conns -= 1
        self._limit_conns()

    async def _CONNECT(self, cr, cw):
        """
        Handle CONNECT command with `poll()`
        NOTE: Only works with MicroPython asyncio
        """
        task = asyncio.current_task()
        bytecnt = 0
        rw = rr = None

        try:
            # remote reader, remote writer
            rr, rw = await _open_connection(task.dst_domain, task.dst_port, local_addr=self.bind)

            # exhaust socket input before opening a new connection
            while line := await cr.readline():
                bytecnt += len(line)
                if line == b'\r\n':
                    break

            bytecnt += await send_http_response(cw, 200, b'Connection established', [b'Proxy-Agent: uProxy/%0.1f' % VERSION])

        except Exception as err:
            self._log(LOG_INFO, "  error, %s" % repr(err))
            ss_ensure_close(rw)
            ss_ensure_close(cw)
            return bytecnt

        pobj = select.poll()
        pobj.register(cr.s, select.POLLIN)
        pobj.register(rr.s, select.POLLIN)

        buf = bytearray(self.bufsize)
        mv = memoryview(buf)

        # forward sockets
        finish = False
        while True:
            for sock, evt in pobj.ipoll(0):
                if evt==select.POLLIN:

                    if sock==cr.s:
                        msg = "send"
                        reader = cr
                        writer = rw
                    else:
                        msg = "recv"
                        reader = rr
                        writer = cw

                    try:
                        n = await asyncio.wait_for(reader.readinto(mv), timeout=self.timeout)
                        if n<=0:
                            finish = True
                            break
                        writer.write(mv[:n])
                        await writer.drain()
                        bytecnt += n
                        self._log(LOG_DEBUG, "  %s %d bytes" % (msg, n))
                    except Exception as err:
                        finish = True
                        self._log(LOG_INFO, "  disconnect, %s" % repr(err))
                        break

                else:
                    # on error
                    finish = True
                    break

            if finish:
                break
            await asyncio.sleep(0)

        ss_ensure_close(cw)
        ss_ensure_close(cw)
        return bytecnt

    async def _CMD(self, cr, cw):
        """
        Generic command handler
        """
        task = asyncio.current_task()
        bytecnt = 0
        rw = rr = None

        try:
            # remote reader, remote writer
            rr, rw = await _open_connection(task.dst_domain, task.dst_port, local_addr=self.bind)

            # assemble new command header
            header = b'%s %s %s' % (task.method, task.path, task.proto)
            rw.write(header)
            # await rw.drain()
            bytecnt += len(header)

            # send rest headers
            while line := await cr.readline():
                # strip proxy header
                if line[:6] == b'Proxy-':
                    line = line[6:]
                rw.write(line)
                bytecnt += len(line)
                # last line
                if line == b'\r\n':
                    break
            await rw.drain()
            self._log(LOG_DEBUG, "  send %d bytes" % bytecnt)

        except Exception as err:
            self._log(LOG_INFO, "  error, %s" % repr(err))
            await ss_ensure_close(rw)
            await ss_ensure_close(cw)
            return bytecnt

        try:
            # get response
            buf = bytearray(self.bufsize)
            mv = memoryview(buf)

            while True:
                n = await asyncio.wait_for(rr.readinto(mv), timeout=self.timeout)
                if n<=0:
                    break
                cw.write(mv[:n])
                bytecnt += n
                self._log(LOG_DEBUG, "  recv %d bytes" % n)
                await asyncio.sleep(0)
            await cw.drain()

        except Exception as err:
            self._log(LOG_INFO, "  disconnect, %s" % repr(err))

        await ss_ensure_close(rw)
        await ss_ensure_close(cw)
        return bytecnt
