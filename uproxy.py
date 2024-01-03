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



async def send_http_response(ss, code, desc="", headers=[], body=None):
    """
    send HTTP response
    """
    try:
        l = b'HTTP/1.1 %d %s\n' % (code, desc)
        ss.write(l)
        for h in headers:
            ss.write(h+b'\n')
        ss.write(b'\n')
        await ss.drain()
    except Exception as err:
        await ss_ensure_close(ss)
        raise err

def ss_get_peername(ss):
    """
    Polyfill of `socket.getpeername()`
    @return: (ip: str, port: int)
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
                ssl=None, loglevel=LOG_INFO, acl_callback=None, auth=None, \
                upstream=None):
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
        try:
            self.upstream_ip, self.upstream_port = upstream.strip().split(':')
            self.upstream_port = int(self.upstream_port)
        except:
            self.upstream_ip = self.upstream_port = None

    async def run(self):
        self._server = await _start_server(self._accept_conn, self.ip, self.port, backlog=self.backlog, ssl=self.ssl)
        self._log(LOG_INFO, "Listening on %s:%d" % (self.ip, self.port))
        await self._server.wait_closed()

    def _log(self, lvl, msg, traceback=0):
        if self.loglevel>=LOG_DEBUG:
            t = asyncio.current_task()
            for i in range(traceback):
                if hasattr(t, '_parent'):
                    t = t._parent
                else:
                    break
            msg = '[%u] %s' % (id(t), msg)
        self.loglevel>=lvl and print(msg)

    def _limit_conns(self):
        """
        Temporarily disable socket polling if number of concurrent connections
        exceed a certain limit so that server's listening socket will no longer
        accept new connections.
        """
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

    async def _forward_data(self, cr,cw, rr,rw):
        """
        Forward between client and remote
        """
        import select
        pobj = select.poll()
        pobj.register(cr.s, select.POLLIN)
        pobj.register(rr.s, select.POLLIN)

        import time
        max_ticks = None if not self.timeout else int(self.timeout*1000)

        try:
            buf = bytearray(self.bufsize)
            mv = memoryview(buf)
            done = False
            start = time.ticks_ms()

            while True:
                for so, evt in pobj.ipoll(0):
                    if evt==select.POLLIN:
                        reader = cr if so==cr.s else rr
                        writer = rw if so==cr.s else cw

                        n = await asyncio.wait_for(reader.readinto(mv), timeout=self.timeout)
                        if n<=0:
                            done = True # remote close socket
                            break
                        writer.write(mv[:n])
                        await writer.drain()
                        if max_ticks:
                            start = time.ticks_ms()

                    else: # on error
                        done = True
                        break

                if done:
                    break

                await asyncio.sleep_ms(0)
                if max_ticks and time.ticks_diff(time.ticks_ms(), start)>max_ticks:
                    raise asyncio.TimeoutError("custom")

        except Exception as err:
            if not isinstance(err, asyncio.TimeoutError):
                self._log(LOG_INFO, "└─disconnect, %s" % repr(err))

        await ss_ensure_close(rw)
        await ss_ensure_close(cw)

    async def handshake(self, cr, cw):
        """
        Perform handshake with client and connect to remote server
        """
        t = asyncio.current_task()
        src_ip, src_port = ss_get_peername(cr)

        #
        # Parse proxy request command
        # * remove 'http://' prefix
        # * seperate path from url
        # * seperate port from url (if any)
        #
        try:
            cmd = await cr.readline() # first line
            if not cmd:
                raise Exception("empty response")
            cmd = cmd.replace(b'\r\n', b'\n')

            method, url, proto = cmd.split(b' ') # `proto` ends with b'\n'
            mv = memoryview(url)
            i = url.find(b'://')
            i = i+3 if i!=-1 else 0
            j = url.find(b'/', i)
            j = j if j!=-1 else len(url)
            path = mv[j:] if mv[j:]!=b'' else b'/'
            domain = mv[i:j]
            k = url.find(b':', i)
            dst_port = int(bytes(mv[k+1:j])) if k!=-1 else 80
            domain = mv[i:k] if k!=-1 else domain
            dst_ip = str(domain, 'ascii')  # placeholder, not a real ip
        except Exception as err:
            self._log(LOG_INFO, "└─error, %s" % repr(err))
            await ss_ensure_close(cw)
            return None, None

        #
        # Access control
        #
        if self.acl_callback and not self.acl_callback(src_ip, src_port, dst_ip, dst_port):
            await ss_ensure_close(cw)
            self._log(LOG_INFO, "BLOCK %s:%d --> %s:%d" % (src_ip, src_port, dst_ip, dst_port))
            return None, None
        else:
            self._log(LOG_INFO, "%s\t%s:%d\t==>\t%s:%d" % (method.decode(), src_ip, src_port, dst_ip, dst_port))

        #
        # Parse proxy request HTTP headers
        #
        rr = rw = None # remote reader, remote writer
        try:
            dst_ip = self.upstream_ip if self.upstream_ip else dst_ip
            dst_port = self.upstream_port if self.upstream_ip else dst_port
            rr, rw = await _open_connection(dst_ip, dst_port, local_addr=self.bind)

            is_auth = not self.auth
            first = True
            while line := await cr.readline():
                line = line.replace(b'\r\n', b'\n')
                mv = memoryview(line)
                last = True if line == b'\n' else False

                if mv[:20]=='Proxy-Authorization:':
                    if self.auth and mv[21:]==self.auth:
                        is_auth = True
                    if not self.upstream_ip:
                        continue

                if self.upstream_ip:
                    # forward all to upstream proxy
                    if first:
                        first = False
                        rw.write(cmd)
                    rw.write(line)
                else:
                    if method==b'CONNECT':
                        # CONNECT
                        if last:
                            await send_http_response(cw, 200, b'Connection established', [b'Proxy-Agent: uProxy/%0.1f' % VERSION])
                    else:
                        # GET/POST/HEAD/OPTION...
                        if first:
                            first = False
                            rw.write(b'%s %s %s' % (method, bytes(path), proto))
                        # strip proxy header
                        rw.write(mv[6:] if mv[:6] == b'Proxy-' else mv)

                if last:
                    await rw.drain()
                    break

            if not is_auth:
                raise Exception('Unauthorized')

        except Exception as err:
            self._log(LOG_INFO, "└─error, %s" % repr(err))
            await ss_ensure_close(rw)
            await ss_ensure_close(cw)
            return None, None

        return rr, rw

    async def _accept_conn(self, cr, cw):
        """
        asyncio version of `connection.accept()`
        Runs on a new task
        """
        self._conns += 1
        await asyncio.sleep(0)
        self._limit_conns()
        await asyncio.sleep(0)
        rr, rw = await self.handshake(cr, cw)
        self._conns -= 1
        await asyncio.sleep(0)
        self._limit_conns()
        await asyncio.sleep(0)

        if not rr:
            return
        await self._forward_data(cr,cw, rr,rw)

        self._log(LOG_DEBUG, "└─close")
