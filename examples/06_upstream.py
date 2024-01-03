#
# Connect to an upstream HTTP(S) proxy
#

import uasyncio as asyncio
import uproxy

proxy = uproxy.uProxy(ip='0.0.0.0', port=8765, upstream='1.2.3.4:8765')
asyncio.run(proxy.run())
