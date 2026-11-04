# tests/test_integration/test_github_app_config.py
"""私钥格式：.env 只能存单行,复原成 PEM 后才能给 githubkit。"""

import importlib

config_mod = importlib.import_module("plugins.builtin.adapters.github-app.config")

PEM_MULTILINE = "-----BEGIN KEY-----\nabc\n-----END KEY-----"


def test_single_line_pem_is_restored():
    single = "-----BEGIN KEY-----\\nabc\\n-----END KEY-----"
    assert config_mod.normalize_pem(single) == PEM_MULTILINE


def test_multiline_pem_untouched():
    assert config_mod.normalize_pem(PEM_MULTILINE) == PEM_MULTILINE


def test_empty_stays_empty():
    assert config_mod.normalize_pem("") == ""
