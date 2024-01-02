#
# Run uProxy with MicroPython
#
# Belows are the recommended parameter values to run on a MCU.
# We want to disable logging also.
#

import uasyncio as asyncio
import uproxy

proxy = uproxy.uProxy(ip='0.0.0.0', port=8765, maxconns=10, backlog=5, bufsize=512, timeout=5, loglevel=0)
asyncio.run(proxy.run())
