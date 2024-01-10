# uProxy - an minimal, memory-efficient HTTP/HTTPS proxy server made for MicroPython
# Copyright (c) 2023 Shawwwn <shawwwn1@gmail.com>
# License: MIT

from .core import *

def __init__():
    attrs = {
        "uHTTP": "http",
        "uSOCKS4": "socks4",
        "uSOCKS5": "socks5",
    }

    for k in attrs:
        try:
            m = getattr(__import__(attrs[k], globals(), locals(), True, 1), k)
            globals()[k] = m
        except ImportError:
            # .py file missing
            pass

__init__()
del __init__
