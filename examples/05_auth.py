# Run HTTP proxy with authentication
#
# Only supports 'Basic' auth mode for now.
#
# Client example reuqest:
# curl -U "kenny:p4ssw0rd" -v "https://ifconfig.me"
#
import sys

impl = sys.implementation.name.lower()
print(impl)

if impl=='cpython':
	import asyncio
	import cproxy as uproxy
else:
	import uasyncio as asyncio
	import uproxy

proxy = uproxy.uHTTP(ip='0.0.0.0', port=8765, auth='kenny:p4ssw0rd')
asyncio.run(proxy.run())
