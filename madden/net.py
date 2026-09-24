"""The engine's one way to open a URL: stock urllib, minus "Connection: close".

urllib.request sends "Connection: close" on every request and gives the caller no way to
turn it off (AbstractHTTPHandler.do_open). Under the Claude Code sandbox every request
goes through a local proxy, and when the server hangs up straight after the last byte
the proxy can drop the tail of the body before relaying it. Measured through that proxy
on 2026-09-11: 10 truncated bodies in 24 large downloads with the header, none in 18
without, whichever client sent it, curl included. The first two sandboxed runs lost
every line fetch to it.

Leaving the header out makes the request keep-alive (the HTTP/1.1 default), so the
server never hangs up first and the body is read to its declared length before the
connection closes. urllib's comment says it forces the header because its response
object would otherwise read until the socket closed; the response class it now uses
stops at Content-Length or the last chunk. Proxies from the environment, redirects and
TLS verification are all urllib's own, unchanged.
"""

from __future__ import annotations

import http.client
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class _NoConnectionClose:
    def request(self, method, url, body=None, headers=None, **kwargs):
        headers = {k: v for k, v in (headers or {}).items() if k.lower() != "connection"}
        super().request(method, url, body, headers, **kwargs)


class _HTTPConnection(_NoConnectionClose, http.client.HTTPConnection):
    pass


class _HTTPSConnection(_NoConnectionClose, http.client.HTTPSConnection):
    pass


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


_OPENER = urllib.request.build_opener(_HTTPHandler, _HTTPSHandler)


def urlopen(url, timeout: float):
    """urllib.request.urlopen without the Connection: close header. url may be a Request."""
    return _OPENER.open(url, timeout=timeout)


# http.client's own words when a proxy answers CONNECT with 403: the proxy refused to
# open the tunnel at all. Cowork's proxy does this for any host off its allowlist.
_PROXY_REFUSED = re.compile(r"Tunnel connection failed: 403\b")


def blocked_hosts(urls, timeout: float = 10) -> list[str]:
    """Hosts this machine's proxy refuses to connect to, by policy, in the order given.

    Any HTTP answer, 404 or 401 included, means the host was reached. A timeout or a
    DNS failure is a hiccup, not policy: it is left to the fetch that needs the host,
    which degrades and warns as before. Only a proxy's refusal comes back, because
    that fails the same way on every run until the allowlist changes.
    """
    blocked: list[str] = []
    for url in urls:
        host = urlsplit(url).hostname
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "madden/1.0"})
            _OPENER.open(req, timeout=timeout).close()
        except urllib.error.HTTPError:
            pass
        except urllib.error.URLError as exc:
            if _PROXY_REFUSED.search(str(exc.reason)) and host not in blocked:
                blocked.append(host)
        except OSError:
            pass
    return blocked
