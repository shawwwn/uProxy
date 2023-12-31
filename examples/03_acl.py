#
# Access Control(ACL) Function Usage
#

import re
import asyncio
import cproxy

def my_acl(src_ip, src_port, dst_ip, dst_port):
    '''
    @dst_ip: could be a domain, use
            `socket.getaddrinfo()` or
            `socket.gethostbyname()`
            to translate it to ip.
    '''
    dst_ip = dst_ip.lower()

    # BLOCK ip NOT from lan to lan or localhost
    from_lan = re.match(r'192\.168\.1\.\d+', src_ip)!=None
    to_lan = re.match(r'192\.168\.1\.\d+', dst_ip)!=None
    to_localhost = dst_ip=='127.0.0.1' or dst_ip=='localhost'
    if not from_lan and (to_lan or to_localhost):
        return False

    # BLOCK client ip
    if src_ip=='104.91.221.151':
        return False

    # BLOCK websites
    blocklist = ['www.known-phish-site.com', 'www.ads-rendezvous.com']
    for dm in blocklist:
        return False

    # ALLOW all by default
    return True

proxy = cproxy.uProxy(ip='0.0.0.0', , port=8765, acl_callback=my_acl)
asyncio.run(proxy.run())
