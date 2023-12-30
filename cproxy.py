#!/usr/bin/env python3
# A CPython wrapper for uProxy
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT
import asyncio
import argparse
import uproxy

#
# Monkey patch - START
#

async def readinto(self, buf):
    """
    Polyfil of `asyncio.StreamWriter.readinto()`
    """
    l = len(buf)
    b = await self.read(l)
    lb = len(b)
    buf[0:lb] = b
    # buf[lb:lb+1] = b'\0'
    return len(b)

asyncio.StreamReader.readinto = readinto


@staticmethod
def _get_peer_info(stream):
    """
    Polyfil of `uproxy.uProxy._get_peer_info`
    @return: (ip, port)
    """
    return stream._transport.get_extra_info('peername')

uproxy.uProxy._get_peer_info = _get_peer_info


@staticmethod
def _open_connection(host, port, ssl=None, server_hostname=None, local_addr=None):
    """
    Bind to ip
    """
    local_addr = (local_addr, 0) if local_addr else None
    return asyncio.open_connection(host=host, port=port, ssl=ssl, server_hostname=server_hostname, local_addr=local_addr)

uproxy.uProxy._open_connection = _open_connection


@staticmethod
async def _start_server(callback, host, port, backlog=5, ssl=None):
    """
    Workability subjects to asyncio version
    Current working asyncio is based on PEP 3156
    """
    server = await asyncio.start_server(client_connected_cb=callback, host=host, port=port, backlog=backlog, ssl=ssl)
    server.s = server._sockets[0] # save listener socket
    return server

uproxy.uProxy._start_server = _start_server


async def _CONNECT_fast(self, creader, cwriter):
    """
    Handle CONNECT command with a go-style coroutine
    NOTE: This handler function is much faster than the poll() based one
    used in uproxy.py but will consume twice the RAM.
    This function can also work in MicroPython.
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
    except ConnectionResetError:
        cwriter.close()
        await writer.wait_closed()
        self.loglevel>=LOG_INFO and print("  close, connection lost")
        return
    except Exception as err:
        raise err

    # connect to remote
    rreader, rwriter = await _open_connection(task.dst_domain, task.dst_port, local_addr=self.bind)

    async def io_copy(reader, writer, msg):
        """
        Forward data from reader to writer
        go-style coroutine
        """
        buf = bytearray(self.bufsize)
        mv = memoryview(buf)
        bytecount = 0
        while True:
            try:
                n = await asyncio.wait_for(reader.readinto(mv), timeout=self.timeout)
            except asyncio.TimeoutError:
                n = -1
            # except: # EBADF
            #   self.loglevel>=uproxy.LOG_INFO and print("  EBADF")
            #   break
            if n>0:
                try:
                    writer.write(mv[:n])
                    await writer.drain()
                except (ConnectionResetError, BrokenPipeError) as err: # Connection lost
                    self.loglevel>=uproxy.LOG_INFO and print("  connection lost, %d bytes transferred" % bytecount)
                    break
            if n<=0:
                writer.close()
                await writer.wait_closed()
                self.loglevel>=uproxy.LOG_DEBUG and print("  pipe close, %d bytes transferred" % bytecount)
                break
            bytecount += n
            self.loglevel>=uproxy.LOG_DEBUG and print("  %s [%s bytes]" % (msg, n))
        return bytecount

    task_c2r = asyncio.create_task(io_copy(creader, rwriter, "client -> remote"))
    task_r2c = asyncio.create_task(io_copy(rreader, cwriter, "client <- remote"))
    results = await asyncio.gather(task_c2r, task_r2c, return_exceptions=False)
    self.loglevel>=uproxy.LOG_DEBUG and print("  close, %d bytes transferred" % sum(results))

uproxy.uProxy._CONNECT = _CONNECT_fast


def limit_connections(self):
    """
    Workability subjects to asyncio version
    Current working asyncio is based on PEP 3156
    """
    if not self.maxconns or self.maxconns<=0:
        return
    elif self._conns>=self.maxconns:
        if self._polling:
            try:
                # first `_selector` is `asyncio.selector_events.BaseSelectorEventLoop` with data and callback
                # second `_selector` is raw `epoll()` selector
                self._server._loop._selector._selector.modify(self._server.s.fileno(), 0)
            except:
                pass
            else:
                self.loglevel>=uproxy.LOG_INFO and print("disable polling")
                self._polling = False
    else:
        if not self._polling:
            try:
                self._server._loop._selector._selector.modify(self._server.s.fileno(), self._server._loop._selector._EVENT_READ)
            except:
                pass
            else:
                self.loglevel>=uproxy.LOG_INFO and print("enable polling")
                self._polling = True

uproxy.uProxy.limit_connections = limit_connections

#
# Monkey patch - END
#






if __name__== "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', help="server ip [%(default)s]", default='0.0.0.0', type=str)
    parser.add_argument('--port', help="server port [%(default)s]", default=8765, type=int)
    parser.add_argument('--bufsize', help="buffer size [%(default)s]", default=4096, type=int)
    parser.add_argument('--maxconns', help="maximum number of concurrent connections, 0 to disable [%(default)s]", metavar='N', default=0, type=int)
    parser.add_argument('--backlog', help="tcp backlog queue size [%(default)s]", metavar='M', default=5, type=int)
    parser.add_argument('--timeout', help="socket timeout [%(default)s]", default=30, type=int)
    parser.add_argument('--loglevel', help="log level (0-quiet, 1-info, 2-debug) [%(default)s]", default=1, type=int)
    parser.add_argument('--bind', help="ip address for outgoing connections to bind to [%(default)s]", default=None, type=str)
    args = parser.parse_args()

    proxy = uproxy.uProxy(ip=args.ip, port=args.port, bind=args.bind, \
                bufsize=args.bufsize, maxconns=args.maxconns, backlog=args.backlog, \
                timeout=args.backlog, loglevel=args.loglevel)
    asyncio.run(proxy.run())
    print("done")
