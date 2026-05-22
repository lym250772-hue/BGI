"""Security defanging — neutralize malicious URLs, IPs, and emails for safe display.

In security workflows, raw links/IPs must be rendered non-clickable to prevent
accidental navigation by analysts, judges, or report readers. This module converts
live indicators into safe-for-display "defanged" forms.

Industry-standard transformations:
  URL:    http://evil.com/path  →  hxxp[://]evil[.]com/path
  IP:     192.168.1.1          →  192[.]168[.]1[.]1
  Email:  bad@phish.com        →  bad@phish[.]com

Usage:
    from analyzer.defanger import defang_text, defang_url, defang_ip

    safe = defang_text("Visit http://bad.com or ping 10.0.0.1")
    # → "Visit hxxp[://]bad[.]com or ping 10[.]0[.]0[.]1"
"""

import re

# ── Patterns ─────────────────────────────────────────────────────────────────
_URL_RE = re.compile(
    r'\b(?:https?|ftp)://'           # scheme
    r'[^\s<>"\'\]\[\{\}\|\\^`]+',    # rest of URL
    re.IGNORECASE,
)

_IP_RE = re.compile(
    r'\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b'
)

_EMAIL_RE = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
)


# ── Core functions ───────────────────────────────────────────────────────────

def defang_url(url: str) -> str:
    """Convert http://evil.com/path → hxxp[://]evil[.]com/path"""
    d = url
    # Replace scheme
    d = re.sub(r'^https?', 'hxxp', d, flags=re.IGNORECASE)
    d = re.sub(r'^ftp', 'fxp', d, flags=re.IGNORECASE)
    # Bracket the ://
    d = d.replace('://', '[://]')
    # Bracket dots in the domain
    d = _bracket_dots_in_host(d)
    return d


def defang_ip(ip: str) -> str:
    """Convert 192.168.1.1 → 192[.]168[.]1[.]1"""
    return _IP_RE.sub(r'\1[.]\2[.]\3[.]\4', ip)


def defang_email(email: str) -> str:
    """Convert bad@phish.com → bad@phish[.]com"""
    # Find the last dot (TLD separator) and bracket it
    at_pos = email.rfind('@')
    if at_pos == -1:
        return email
    domain = email[at_pos + 1:]
    defanged_domain = _bracket_dots_in_host(domain)
    return email[:at_pos + 1] + defanged_domain


def defang_text(text: str) -> str:
    """Defang all URLs, IPs, and emails found in free text.

    Returns the text with all indicators replaced by their defanged forms.
    Safe to call on already-defanged text (idempotent within reason).
    """
    if not text:
        return text

    # Order matters: URLs first (they contain dots that look like IPs),
    # then standalone IPs, then emails.
    text = _URL_RE.sub(lambda m: defang_url(m.group(0)), text)

    # Only defang IPs that aren't inside already-defanged brackets
    def _ip_replacer(m):
        ip = m.group(0)
        # Check if this IP is part of a defanged URL (preceded by [://] or [.)
        start = m.start()
        before = text[max(0, start - 5):start]
        if '[://]' in before or '[.]' in before:
            return ip  # already in a defanged URL, skip
        return defang_ip(ip)

    text = _IP_RE.sub(_ip_replacer, text)
    text = _EMAIL_RE.sub(lambda m: defang_email(m.group(0)), text)

    return text


# ── Helpers ──────────────────────────────────────────────────────────────────

def _bracket_dots_in_host(host: str) -> str:
    """Replace dots in a host/domain portion with [.]"""
    # Remove existing brackets first (idempotent)
    host = host.replace('[.]', '.')
    return host.replace('.', '[.]')


# ── Reverse (re-arm) for processing ──────────────────────────────────────────

def refang(text: str) -> str:
    """Reverse defanging: hxxp[://]evil[.]com → http://evil.com

    Used internally before passing URLs to scanners/downloaders.
    """
    if not text:
        return text
    d = text
    d = d.replace('[://]', '://')
    d = d.replace('[.]', '.')
    d = re.sub(r'^hxxp', 'http', d, flags=re.IGNORECASE)
    d = re.sub(r'^fxp', 'ftp', d, flags=re.IGNORECASE)
    return d
