# tests/test_integration/test_netenv.py
"""NO_PROXY 规范化:httpx 吃不下带方括号的 IPv6 条目。"""

import os

from engine.shared import netenv


def test_bracketed_ipv6_is_unwrapped():
    raw = "localhost,127.0.0.1,::1,[::1]"
    assert netenv.normalize_no_proxy(raw) == "localhost,127.0.0.1,::1,::1"


def test_plain_entries_untouched():
    raw = "localhost,127.0.0.1,.internal"
    assert netenv.normalize_no_proxy(raw) == raw


def test_bracketed_ipv6_with_port_left_alone():
    raw = "[::1]:8080,localhost"
    assert netenv.normalize_no_proxy(raw) == "[::1]:8080,localhost"


def test_empty_parts_dropped():
    assert netenv.normalize_no_proxy(" , localhost , ") == "localhost"


def test_prepare_proxy_env_is_idempotent(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,[::1]")
    netenv.prepare_proxy_env()
    assert os.environ["NO_PROXY"] == "localhost,::1"
    netenv.prepare_proxy_env()
    assert os.environ["NO_PROXY"] == "localhost,::1"
