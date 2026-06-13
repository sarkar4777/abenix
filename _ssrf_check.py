import ipaddress
from urllib.parse import urlparse

tests = [
    "http://2130706433/admin",
    "http://0x7f.0x0.0x0.0x1/admin",
    "http://169.254.169.254.nip.io/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "https://169.254.169.254%23@evil.example.com/",
    "http://169.254.169.254/",
    "http://127.0.0.1/",
]
for url in tests:
    u = urlparse(url)
    host = (u.hostname or "").strip()
    print("URL=" + repr(url))
    print("  hostname=" + repr(host))
    try:
        ip = ipaddress.ip_address(host)
        flags = []
        if ip.is_private: flags.append("private")
        if ip.is_loopback: flags.append("loopback")
        if ip.is_link_local: flags.append("link_local")
        print("  parsed_ip=" + str(ip) + " flags=" + str(flags))
    except ValueError as e:
        print("  not_an_ip_literal: " + str(e))
    print()
