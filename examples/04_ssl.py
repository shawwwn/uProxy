#
# Start a HTTPS proxy server with CPython
#

import ssl
import asyncio
import cproxy

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain('server.crt', keyfile='server.key')
ctx.load_verify_locations(cafile='ca-certificates.crt')
ctx.check_hostname = False
ctx.verify_mode = ssl.VerifyMode.CERT_REQUIRED

proxy = cproxy.uProxy(ip='0.0.0.0', port=8765, ssl=ctx)
asyncio.run(proxy.run())
