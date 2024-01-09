#!/usr/bin/env python3
# Run uProxy with CPython
#
# Note that we are importing `cproxy` instead of `uproxy`
# Setting `maxconns` to 0 to use OS max connection limit per socket.
#
import asyncio
import cproxy

# start all three proxies at once
http_proxy = cproxy.uHTTP(ip='0.0.0.0', port=8765, maxconns=0, backlog=100, bufsize=8192, timeout=30, loglevel=1)
socks4_proxy = cproxy.uSOCKS4(ip='0.0.0.0', port=8766, maxconns=0, backlog=100, bufsize=8192, timeout=30, loglevel=1)
socks5_proxy = cproxy.uSOCKS5(ip='0.0.0.0', port=8767, maxconns=0, backlog=100, bufsize=8192, timeout=30, loglevel=1)

async def main():
	asyncio.create_task(socks4_proxy.run())
	asyncio.create_task(socks5_proxy.run())
	await http_proxy.run()

asyncio.run(main())
