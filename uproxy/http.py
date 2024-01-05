# HTTP/HTTPS proxy for uproxy module
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT

try:
    import uasyncio as asyncio
except:
    import asyncio
from . import core

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

class uHTTP(core.uProxy):
    """
    HTTP(S) Proxy server class for uProxy
    """

    async def _handshake(self, cr, cw):
        """
        HTTP(S) handshake
        """
        src_ip, src_port = core.ss_get_peername(cr)

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
            self._log(core.LOG_INFO, "└─error, %s" % repr(err))
            await core.ss_ensure_close(cw)
            return None, None

        #
        # Access control
        #
        if self.acl_callback and not self.acl_callback(src_ip, src_port, dst_ip, dst_port):
            await core.ss_ensure_close(cw)
            self._log(core.LOG_INFO, "BLOCK %s:%d --> %s:%d" % (src_ip, src_port, dst_ip, dst_port))
            return None, None
        else:
            self._log(core.LOG_INFO, "%s\t%s:%d\t==>\t%s:%d" % (method.decode(), src_ip, src_port, dst_ip, dst_port))

        #
        # Parse proxy request HTTP headers
        #
        rr = rw = None # remote reader, remote writer
        try:
            dst_ip = self.upstream_ip if self.upstream_ip else dst_ip
            dst_port = self.upstream_port if self.upstream_ip else dst_port
            rr, rw = await core._open_connection(dst_ip, dst_port, local_addr=self.bind)

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
                            await send_http_response(cw, 200, b'Connection established', [b'Proxy-Agent: uProxy/%0.1f' % core.VERSION])
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
                raise Exception('unauthorized')

        except Exception as err:
            self._log(core.LOG_INFO, "└─error, %s" % repr(err))
            await core.ss_ensure_close(rw)
            await core.ss_ensure_close(cw)
            return None, None

        return rr, rw
