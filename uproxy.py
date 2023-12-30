#!/usr/bin/env micropython
# uProxy - an minimal, memory-efficient HTTP/HTTPS proxy server made for
# MicroPython
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT
import select
import struct
try:
    import uasyncio as asyncio
except:
    import asyncio

LOG_NONE = 0
LOG_INFO = 1
LOG_DEBUG = 2

class uProxy:
    def __init__(self, ip='0.0.0.0', port=8765, bind=None, \
                bufsize=4096, maxconns=0, backlog=5, timeout=30, \
                loglevel=LOG_INFO):
        self.ip = ip
        self.port = port
        self.bind = bind
        self.bufsize = bufsize
        self.maxconns = maxconns
        self.backlog = backlog
        self.loglevel = loglevel        # 0-silent, 1-normal, 2-debug
        self.timeout = timeout          # seconds
        self._server = None
        self.acl_callback = None
        self._conns = 0                 # current connection count
        self._polling = True            # server socket polling availability

    async def run(self):
        self._server = await self._start_server(self.accept_connection, self.ip, self.port, backlog=self.backlog)
        self.loglevel>=LOG_INFO and print("Listening on %s:%d" % (self.ip, self.port))
        await self._server.wait_closed()

    @staticmethod
    def _parse_header(line):
        """
        Header is the first line of the incoming HTTP request
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

    @staticmethod
    def _get_peer_info(stream):
        mv = memoryview(stream.get_extra_info('peername'))
        _, port, a, b, c, d = struct.unpack('!HHBBBB', mv[0:8])
        ip = '%u.%u.%u.%u' % (a, b, c, d)
        return ip, port

    @staticmethod
    def _open_connection(host, port, ssl=None, server_hostname=None, local_addr=None):
        """
        Modified from `uasyncio.open_connection()`
        - Add `local_addr` parameter
        TODO: Remove this function once micropython adds ip binding
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

    @staticmethod
    async def _start_server(cb, host, port, backlog=5, ssl=None):
        """
        Modified from `uasyncio.start_server()`
        - Add socket to `Server' instance
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

    def limit_connections(self):
        """
        Temporarily disable socket polling if number of concurrent connections
        exceed a certain limit, so that server's listening socket will no longer
        accept new connections.
        This will cause some connection loss errors. More error handling is
        needed.
        """
        if not self.maxconns or self.maxconns<=0:
            return
        elif self._conns>=self.maxconns:
            if self._polling:
                try:
                    asyncio.core._io_queue.poller.modify(self._server.s, 0)
                except:
                    pass
                else:
                    self.loglevel>=LOG_INFO and print("disable polling")
                    self._polling = False
        else:
            if not self._polling:
                try:
                    asyncio.core._io_queue.poller.modify(self._server.s, select.POLLIN)
                except:
                    pass
                else:
                    self.loglevel>=LOG_INFO and print("enable polling")
                    self._polling = True

    async def accept_connection(self, creader, cwriter):
        """
        Non-blocking version of `connection.accept()`
        Runs on a new task
        @creader: stream reader of client socket
        @cwriter: stream writer of client socket
        """
        self._conns += 1
        self.limit_connections()

        src_ip, src_port = self._get_peer_info(creader)

        # parse proxy header
        header = await creader.readline()
        if not header:
            cwriter.close()
            await cwriter.wait_closed()
            return
        method, dst_domain, dst_port, path, proto = self._parse_header(header)
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
        if self.acl_callback and not acl_callback(src_ip, src_port, dst_ip, dst_port):
            cwriter.close()
            await cwriter.wait_closed()
            print("BLOCK %s:%d --> %s:%d" % (src_ip, src_port, dst_ip, dst_port))
            return
        self.loglevel>=LOG_INFO and print("%s\t%s:%d\t==>\t%s:%d" % (task.method.decode(), src_ip, src_port, dst_ip, dst_port))

        # serve commands
        if method==b'CONNECT':
            await self._CONNECT(creader, cwriter)
        else:
            await self._CMDS(creader, cwriter)

        self._conns -= 1
        self.limit_connections()

    async def _CONNECT(self, creader, cwriter):
        """
        Handle CONNECT command with `poll()`
        NOTE: Only works with MicroPython's asyncio
        """
        task = asyncio.current_task()

        # exhaust socket input before opening a new connection
        try:
            while line := await creader.readline():
                if line == b'\r\n':
                    break
            cwriter.write(b'HTTP/1.1 200 Connection established\r\n')
            cwriter.write(b'\r\n')
            await cwriter.drain()
        except BrokenPipeError:
            cwriter.close()
            await writer.wait_closed()
            self.loglevel>=LOG_INFO and print("  close, broken pipe")
            return
        except Exception as err:
            raise err

        # connect to remote
        rreader, rwriter = await self._open_connection(task.dst_domain, task.dst_port, local_addr=self.bind)

        pobj = select.poll()
        pobj.register(creader.s, select.POLLIN)
        pobj.register(rreader.s, select.POLLIN)

        buf = bytearray(self.bufsize)
        mv = memoryview(buf)
        bytecount = 0

        # forward sockets
        finish = False
        while True:
            for sock, evt in pobj.ipoll(0):
                if evt==select.POLLIN:
                    if sock==creader.s:
                        reader = creader
                        writer = rwriter
                        msg = "client -> remote"
                    else:
                        reader = rreader
                        writer = cwriter
                        msg = "client <- remote"
                    try:
                        n = await asyncio.wait_for(reader.readinto(mv), timeout=60)
                    except asyncio.TimeoutError:
                        n = -1
                    if n<=0:
                        finish = True
                        break
                    try:
                        writer.write(mv[:n])
                        await writer.drain()
                    except: # TODO: better handle BrokenPipe error
                        self.loglevel>=LOG_INFO and print("  close, broken pipe")
                        finish = True
                        break
                    bytecount += n
                    self.loglevel>=LOG_DEBUG and print("  %s [%d bytes]" % (msg, n))
                else:
                    # on error
                    finish = True
                    break

            if finish:
                break
            await asyncio.sleep(0)

        cwriter.close()
        await cwriter.wait_closed()
        rwriter.close()
        await rwriter.wait_closed()
        self.loglevel>=LOG_DEBUG and print("  close, %s bytes transfered" % bytecount)

    async def _CMDS(self, creader, cwriter):
        """
        Default command handler
        """
        task = asyncio.current_task()
        bytecount = 0

        # connect to remote
        rreader, rwriter = await self._open_connection(task.dst_domain, task.dst_port, local_addr=self.bind)

        # assemble & send request
        header = b'%s %s %s' % (task.method, task.path, task.proto)
        rwriter.write(header)
        await rwriter.drain()
        bytecount += len(header)

        # send rest HTTP headers
        while line := await creader.readline():
            if line[:6] == b'Proxy-':
                line = line[6:] # strip proxy header
            rwriter.write(line)
            bytecount += len(line)
            if line == b'\r\n':
                break # last line
        await rwriter.drain()
        self.loglevel>=LOG_DEBUG and print("  client -> remote [%d bytes]" % bytecount)

        # get response
        buf = bytearray(self.bufsize)
        mv = memoryview(buf)
        while True:
            try:
                n = await asyncio.wait_for(rreader.readinto(mv), timeout=self.timeout)
            except asyncio.TimeoutError:
                n = -1
            if n<=0:
                rwriter.close()
                await rwriter.wait_closed()
                break
            cwriter.write(mv[:n])
            bytecount += n
            self.loglevel>=LOG_DEBUG and print("  remote -> client [%d bytes]" % n)
            await asyncio.sleep(0)
        await cwriter.drain()
        cwriter.close()
        await cwriter.wait_closed()
        self.loglevel>=LOG_DEBUG and print("  close, %s bytes transfered" % bytecount)
