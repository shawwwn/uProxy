#
# Run uProxy with CPython
#
# Note that we are importing `cproxy` instead of `uproxy`
# Setting `maxconns` to 0 means we are using OS's max connection limit per socket.
# We want to enable debug print.
#

import asyncio
import cproxy

proxy = cproxy.uProxy(ip='0.0.0.0', port=8765, maxconns=0, backlog=100, bufsize=8192, timeout=30, loglevel=2)
asyncio.run(proxy.run())
