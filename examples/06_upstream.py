# Connect to an upstream proxy
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

proxy = uproxy.uHTTP(ip='0.0.0.0', port=8765, upstream='1.2.3.4:8765')
asyncio.run(proxy.run())
