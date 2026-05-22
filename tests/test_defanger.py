"""Unit tests for defanger module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from analyzer.defanger import defang_url, defang_ip, defang_email, defang_text, refang


def test_defang_url():
    assert defang_url("http://evil.com/path") == "hxxp[://]evil[.]com/path"
    assert defang_url("https://bad.org") == "hxxp[://]bad[.]org"


def test_defang_url_ftp():
    assert defang_url("ftp://files.example.com") == "fxp[://]files[.]example[.]com"


def test_defang_ip():
    assert defang_ip("192.168.1.1") == "192[.]168[.]1[.]1"
    assert defang_ip("10.0.0.1") == "10[.]0[.]0[.]1"


def test_defang_email():
    assert defang_email("bad@phish.com") == "bad@phish[.]com"
    assert defang_email("user@sub.example.org") == "user@sub[.]example[.]org"


def test_defang_text_full():
    text = "Visit http://evil.com or ping 10.0.0.1 or email bad@phish.com"
    safe = defang_text(text)
    assert "hxxp[://]evil[.]com" in safe
    assert "10[.]0[.]0[.]1" in safe
    assert "bad@phish[.]com" in safe


def test_defang_text_already_defanged():
    """Already-defanged text should remain mostly unchanged (idempotent)."""
    already = "hxxp[://]evil[.]com and 192[.]168[.]1[.]1"
    safe = defang_text(already)
    assert "hxxp[://]evil[.]com" in safe


def test_refang():
    assert refang("hxxp[://]evil[.]com") == "http://evil.com"
    assert refang("192[.]168[.]1[.]1") == "192.168.1.1"


def test_defang_empty():
    assert defang_text("") == ""
    assert defang_text(None) is None
