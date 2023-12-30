# uProxy
A minimal, memory-efficient HTTP/HTTPS proxy server designed to run in some of the most memory-constraint environments such as inside an MCU.\
Originally written for MicroPython, but made compatible with CPython.

> [!IMPORTANT]
> This proxy is still in beta, stability is not guaranteed.\
> If you encounter any exception or crash at runtime, feel free to drop me an issue or PR.\
> PR is of utmost welcome here!

## Usage (MicroPython):

```py
import uasyncio as asyncio
import uproxy
proxy = uproxy.uProxy(ip='0.0.0.0', port=8765)
asyncio.run(proxy.run())
```

## Usage (CPython):

```
cproxy.py [-h] [--ip IP] [--port PORT] [--bufsize BUFSIZE] [--maxconns N] [--backlog M] [--timeout TIMEOUT]
                 [--loglevel LOGLEVEL] [--bind BIND]
```

> [!NOTE]
> `cproxy.py` is a CPython-compatible wrapper of `uproxy.py` for launching uproxy in a terminal.


```console
$ python3 cproxy.py --ip 0.0.0.0 --port 8765
Listening on 0.0.0.0:8765
CONNECT 192.168.1.230:54309     ==>     ifconfig.me:443
GET     192.168.1.230:54312     ==>     ifconfig.me:80
CONNECT 192.168.1.230:54315     ==>     www.google.com:443
```

## API docs:

* **`uproxy.uProxy(ip, port, bind, bufsize, maxconns, backlog, timeout, loglevel)`**

  Initialize proxy server

  * **ip** - server ip [0.0.0.0]
  * **port** - server port [8765]
  * **bind** - ip address for outgoing connections to bind to [None]
  * **bufsize** - buffer size of each connection, in bytes [4096]
  * **maxconns** - max number of ***accepted*** connections that are being processed, 0 to disable [0]
  * **backlog** - max number of ***unaccepted*** connections waiting to be processed [5]
  * **timeout** - connection timeout, in seconds [30]
  * **loglevel** - log level (0-quiet, 1-info, 2-debug) [1]

* **`uProxy.run()`**

  Start proxy server.\
  Need to be run in an asyncio event loop

* **`uProxy.acl_callback`**

  The access control callback function takes a 4-tuple input, they are source ip/port, destination ip/port.\
  Default value `None` means always allow all connection to pass.\
  It's recommended to set right after the creation of `uProxy` instance.\
  Return `True` to allow current connection to pass, return `False` to block it.
  ```py
  def acl_callback(src_ip: str, src_port: int, dst_ip: str, dst_port: int) -> bool
  ```

## Other:

+ To use it with MicroPython, only need to copy `uproxy.py`.
+ To use it with CPython, copy both files and use `cproxy.py`.
+ `cproxy.py` replaces some core logic of `uproxy.py`, making it run much faster, at the expense of 2x memory consumption.
+ For detail usage, please refer to `examples/`
  
## Todo:
- [ ] Authentication
- [ ] Forward to upstream proxy
- [ ] HTTPS server
