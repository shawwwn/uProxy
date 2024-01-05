# µProxy
A minimal, memory-efficient HTTP(S)/SOCKS4(a) proxy server designed to run in memory-constraint environments.\
Originally written for MicroPython, now compatible with CPython.

## features
* HTTP/HTTPS protocol (all commands supported)
* SOCKS4(a) protocol (all commands supported)
* Maximum connection limit
* Modular architecture
* CPython-compatiable

## Usage (MicroPython):

```py
import asyncio
import uproxy

# Run a HTTP(S) proxy server at port 8765
proxy = uproxy.uHTTP(ip='0.0.0.0', port=8765)
asyncio.run(proxy.run())
```

Change `uHTTP` into `uSOCKS4` or `uSOCKS5` if you want a SOCKS proxy.

## Usage (CPython):

`cproxy.py` is a CPython-compatible wrapper of `uproxy.py` for running uproxy in console.

```
cproxy.py [-h] [-v] [--proto PROTO] [--ip IP] [--port PORT] [--bind BIND]
          [--bufsize BUFSIZE] [--maxconns N] [--backlog M]
          [--timeout TIMEOUT] [--loglevel LOGLEVEL]
          [--auth AUTH] [--upstream UPSTREAM]
```

Available values for argument `--proto` is `HTTP`,`SOCKS4`, and `SOCKS5`. \
Rest of the arguments' values are the same as in [api docs](#api-docs).

```console
$ python3 cproxy.py --proto HTTP --ip 0.0.0.0 --port 8765
Listening on 0.0.0.0:8765
CONNECT 192.168.1.230:54309     ==>     ifconfig.me:443
GET     192.168.1.230:54312     ==>     ifconfig.me:80
CONNECT 192.168.1.230:54315     ==>     www.google.com:443
```

To use `cproxy.py` in code:

```py
import asyncio
import cproxy
proxy = cproxy.uHTTP()
asyncio.run(proxy.run())
```

## API docs:

* **`uproxy.uHTTP(ip='0.0.0.0', port=8765, bind=None, bufsize=8192, maxconns=0, backlog=100, timeout=30, ssl=None, loglevel=1, acl_callback=None, auth=None, upstream=None)`**

  Initialize proxy server

  * **ip** - server ip
  * **port** - server port
  * **bind** - ip address for outgoing connections to bind to
  * **bufsize** - buffer size of each connection, in bytes
  * **maxconns** - max number of ***accepted*** connections server can handle, 0 to disable
  * **backlog** - max number of ***unaccepted*** connections waiting to be processed
  * **timeout** - connection timeout, in seconds
  * **loglevel** - log level (0-quiet, 1-info, 2-debug)
  * **ssl** - a SSLContext object to start a HTTPS server
  * **acl_callback** - access control callback function
  * **auth** - an 'user:password' pair that clients need to provide in order to authenticate with server
  * **upstream** - an 'ip:port' pair to connect to as an upstream HTTP proxy

* **`uHTTP.run()`**

  Start proxy server.\
  Need to run in an asyncio event loop

* **`uHTTP.acl_callback`**

  The access control callback function takes a 4-tuple input (source ip/port and destination ip/port).\
  Return `True` to allow current connection to pass, return `False` to block it.\
  Default value `None` means always allow all connection to pass.
  ```py
  def acl_callback(src_ip: str, src_port: int, dst_ip: str, dst_port: int) -> bool
  ```

* **`uproxy.SOCKS4(ip='0.0.0.0', port=8765, bind=None, bufsize=8192, maxconns=0, backlog=100, timeout=30, ssl=None, loglevel=1, acl_callback=None, auth=None, upstream=None)`**
  
  Same as `uHTTP`

  * **upstream** - forward to an upstream SOCKS4 proxy

* **`uproxy.SOCKS5(ip='0.0.0.0', port=8765, bind=None, bufsize=8192, maxconns=0, backlog=100, timeout=30, ssl=None, loglevel=1, acl_callback=None, auth=None, upstream=None)`**

  TODO: to be implemented

  * **upstream** - forward to an upstream SOCKS5 proxy

## Notes:

+ To use it with MicroPython, only copy `uproxy/` directory.
+ To use it with CPython, copy both the directory and `cproxy.py`, start with the file.
+ Remove `<protocol_name>.py` from `uproxy/` if you don't need this protocol, this helps reduce code size.
+ `cproxy.py` replaces some core logic of `uproxy.py`, making it run much faster, at the expense of 2x memory consumption.
+ The `upstream` parameter only forwards traffic to an upstream proxy with the same protocol. Mixing protocols is not supported. Feel free to contribute ;)
+ A set of paramters for a memory-constraint environment should be `maxconns=10, backlog=5, bufsize=512, timeout=5`.
+ For detail usage, please refer to `examples/`

## Todo:
- [X] Authorization
- [X] Forward to upstream proxy
- [X] HTTPS server
- [X] SOCKS4 (CONNECT/BIND)
- [ ] SOCKS4 upstream
- [ ] SOCKS5 (CONNECT/BIND/UDP_ASSOCIATE)
- [ ] SOCK5 upstream
