#
# Run uProxy with authentication
# Clients need to provide correct username and password to use proxy.
# Only supports 'Basic' authentication mode for now.
#
# Client Reuqest:
# curl -U "kenny:p4ssw0rd" -v "https://ifconfig.me"
#

import uasyncio as asyncio
import uproxy

proxy = uproxy.uProxy(ip='0.0.0.0', port=8765, auth='username:password')
asyncio.run(proxy.run())
