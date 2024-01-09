#
# Run uProxy with MicroPython
#
import uasyncio as asyncio
import uproxy

proxy = uproxy.uHTTP(ip='0.0.0.0', port=8765, maxconns=10, backlog=5, bufsize=512, timeout=5)

asyncio.run(proxy.run())
