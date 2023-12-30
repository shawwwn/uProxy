# uProxy
A minimal, memory-efficient HTTP/HTTPS proxy server for MicroPython, compatible with CPython.

## Usage (MicroPython):

```py
import uasyncio as asyncio
import uproxy
proxy = uproxy.uProxy(ip='0.0.0.0', port=8765)
asyncio.run(proxy.run())
```

## Usage (CPython):

`cproxy.py` is a CPython wrapper for launching proxy in terminal.

```console
$ python3 cproxy.py --ip 0.0.0.0 --port 8765
Listening on 0.0.0.0:8765
CONNECT 192.168.1.230:54309     ==>     ifconfig.me:443
GET     192.168.1.230:54312     ==>     ifconfig.me:80
CONNECT 192.168.1.230:54315     ==>     www.google.com:443
```


