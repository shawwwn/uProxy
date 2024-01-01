#!/usr/bin/env micropython
# uProxy - an minimal, memory-efficient HTTP/HTTPS proxy server made for MicroPython
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT
#
# > MicroPython only!
# > For CPython-compatible uProxy, refer to `cproxy.py`
#
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

def b64(text, enc=True):
    """
    Turn text into base64 encoding, vice versa
    @text: username:password
    @enc: True to encode, False to decode
    """
    from ubinascii import b2a_base64, a2b_base64
    if enc:
        return b2a_base64(text)[:-1]
    else:
        return a2b_base64(text)[:-1]



class uProxy:
    """
    Proxy Server
    """

    def __init__(self, ip='0.0.0.0', port=8765, bind=None, \
                bufsize=8192, maxconns=0, backlog=100, timeout=30, \
                ssl=None, loglevel=LOG_INFO, acl_callback=None, auth=None):
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
        self.auth = b'Basic '+b64(auth, True) if auth else None

    async def run(self):
        self._server = await _start_server(self._accept_conn, self.ip, self.port, backlog=self.backlog, ssl=self.ssl)
        self._log(LOG_INFO, "Listening on %s:%d" % (self.ip, self.port))
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

    def _authorize(self, line):
        """
        Check whether the incoming http header is authorized
        @line is a line from http headers
        """
        if self.auth and line:
            if line[20:].strip() == self.auth:
                return True
        return False

    async def _accept_conn(self, cr, cw):
        """
        Non-blocking version of `connection.accept()`
        Runs on a new task
        @cr: stream reader for client socket
        @cw: stream writer for client socket
        """
        self._conns += 1
        self._limit_conns()

        src_ip, src_port = ss_get_peername(cr)

        # parse proxy header
        try:
            header = await cr.readline()
            if not header:
                raise Exception("Empty Response")
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
            await self._CONNECT(cr, cw)
        else:
            await self._CMD(cr, cw)
        self._log(LOG_DEBUG, "  close")

        self._conns -= 1
        self._limit_conns()

    async def _prepare_cmd(self, cr, cw, callback):
        """
        Process client request's HTTP header line by line
        Connect to dst domain, return remote socket's r/w
        """
        task = asyncio.current_task()
        rr = rw = None # remote reader, remote writer

        try:
            rr, rw = await _open_connection(task.dst_domain, task.dst_port, local_addr=self.bind)

            is_auth = not self.auth
            while line := await cr.readline():
                if self._authorize(line):
                    is_auth = True
                    continue
                await callback(line, rr, rw)
                if line == b'\r\n':
                    break

            if not is_auth:
                raise Exception('Unauthorized')

        except Exception as err:
            self._log(LOG_INFO, "  error, %s" % repr(err))
            await ss_ensure_close(rw)
            await ss_ensure_close(cw)
            return None, None

        return rr, rw

    async def _CONNECT(self, cr, cw):
        """
        Handle CONNECT command with `poll()`
        NOTE: Only works with MicroPython asyncio
        """
        async def __cb(line, rr, rw):
            # last line
            if line == b'\r\n':
                await send_http_response(cw, 200, b'Connection established', [b'Proxy-Agent: uProxy/%0.1f' % VERSION])

        rr, rw = await self._prepare_cmd(cr, cw, __cb)
        if not rr:
            return

        import select
        pobj = select.poll()
        pobj.register(cr.s, select.POLLIN)
        pobj.register(rr.s, select.POLLIN)

        # forward data
        try:
            buf = bytearray(self.bufsize)
            mv = memoryview(buf)

            while True:

                for so, evt in pobj.ipoll(0):
                    if evt==select.POLLIN:

                        reader = cr if so==cr.s else rr
                        writer = rw if so==cr.s else cw

                        n = await asyncio.wait_for(reader.readinto(mv), timeout=self.timeout)
                        if n<=0:
                            break
                        writer.write(mv[:n])
                        await writer.drain()

                    else: # on error
                        break

                await asyncio.sleep(0)

        except Exception as err:
            self._log(LOG_INFO, "  disconnect, %s" % repr(err))

        await ss_ensure_close(rw)
        await ss_ensure_close(cw)

    async def _CMD(self, cr, cw):
        """
        Generic command handler
        """
        first = True
        async def __cb(line, rr, rw):
            nonlocal first
            if first: # first line
                first = False
                t = asyncio.current_task()
                cmd = b'%s %s %s' % (t.method, t.path, t.proto)
                rw.write(cmd) # write command header

            # strip proxy header
            mv = memoryview(line)
            rw.write(mv[6:] if mv[:6] == b'Proxy-' else mv)

            if line == b'\r\n': # last line
                await rw.drain()

        rr, rw = await self._prepare_cmd(cr, cw, __cb)
        if not rr:
            return

        # relay remote response to client
        try:
            buf = bytearray(self.bufsize)
            mv = memoryview(buf)

            while True:
                n = await asyncio.wait_for(rr.readinto(mv), timeout=self.timeout)
                if n<=0:
                    break
                cw.write(mv[:n])
                await asyncio.sleep(0)
            await cw.drain()

        except Exception as err:
            self._log(LOG_INFO, "  disconnect, %s" % repr(err))

        await ss_ensure_close(rw)
        await ss_ensure_close(cw)
