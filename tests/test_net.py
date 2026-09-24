"""The up-front network check: a proxy's refusal is policy; anything else is a hiccup."""

from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from madden import net


class _Opener:
    """Answers each URL the way a real network would: an outcome per host."""

    def __init__(self, outcomes):
        self.outcomes, self.asked = outcomes, []

    def open(self, req, timeout):
        self.asked.append((req.get_method(), req.full_url))
        outcome = self.outcomes[req.host]
        if isinstance(outcome, BaseException):
            raise outcome
        return io.BytesIO(b"")


# What Cowork's proxy produced in week 3, as urllib reports it.
REFUSED = urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))


def test_a_proxy_refusal_is_reported(monkeypatch):
    opener = _Opener({"api.the-odds-api.com": REFUSED, "github.com": None})
    monkeypatch.setattr(net, "_OPENER", opener)
    assert net.blocked_hosts(["https://github.com/x", "https://api.the-odds-api.com/v4"]) \
        == ["api.the-odds-api.com"]
    assert all(method == "HEAD" for method, _ in opener.asked)


def test_any_http_answer_means_the_host_was_reached(monkeypatch):
    not_found = urllib.error.HTTPError("https://api.the-odds-api.com/v4", 404, "Not Found",
                                       {}, None)
    monkeypatch.setattr(net, "_OPENER", _Opener({"api.the-odds-api.com": not_found}))
    assert net.blocked_hosts(["https://api.the-odds-api.com/v4"]) == []


def test_a_hiccup_is_not_a_refusal(monkeypatch):
    """Left to the fetch that meets it, which degrades and warns as before."""
    monkeypatch.setattr(net, "_OPENER", _Opener({
        "api.open-meteo.com": urllib.error.URLError(TimeoutError("timed out")),
        "github.com": urllib.error.URLError(OSError("nodename nor servname provided")),
        "api.the-odds-api.com": TimeoutError("timed out")}))
    assert net.blocked_hosts(["https://api.open-meteo.com/v1/forecast",
                              "https://github.com/x",
                              "https://api.the-odds-api.com/v4"]) == []


def test_a_proxy_that_errs_rather_than_refuses_is_a_hiccup(monkeypatch):
    bad_gateway = urllib.error.URLError(OSError("Tunnel connection failed: 502 Bad Gateway"))
    monkeypatch.setattr(net, "_OPENER", _Opener({"github.com": bad_gateway}))
    assert net.blocked_hosts(["https://github.com/x"]) == []
