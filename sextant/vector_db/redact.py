"""
Hide credentials and identity numbers in everything this server hands out.

The library stays as the user's files have it: the index, the keyword search
and the self-test all work on the real text, on the user's machine. What an
assistant receives from a tool is the same text with card numbers, CVVs,
passwords, PINs, one-time codes, keys and tokens, and government or bank
identity numbers replaced by a marker that names what was there, such as
``[hidden: CVV]``. There is no argument that turns this off: a tool argument
is written by the assistant, and the assistant can be talked into anything.

Names, addresses, dates of birth, phone numbers and e-mail addresses are left
alone. They are what most questions about one's own documents are about
(which address is newer, what a certificate says), and the search tool's own
instructions depend on them being readable.

What is matched, and why each check is shaped the way it is:

- A card number is 13-19 digits that pass the Luhn check, so an order number
  or a phone number is not taken for one.
- An Aadhaar number is 12 digits, not starting 0 or 1, that pass the Verhoeff
  check UIDAI uses. With the word Aadhaar (or UID, VID) in front, any 12 or 16
  digits are hidden, since text recognition can break a checksum.
- A PAN is the ABCDE1234F shape with a holder letter in the fourth place.
- Keys with a published prefix (Anthropic, OpenAI, AWS, Google, GitHub,
  GitLab, Slack), JSON web tokens, private-key blocks and the password in a
  ``user:password@host`` address are hidden wherever they appear.
- Everything else -- CVV, password, PIN, OTP, an api key or token, a bank
  account, passport, voter ID or driving licence number -- is hidden only
  where its label stands in front of it. "Password: hunter2" loses its value;
  "forgot your password?" is untouched, and so is "PIN code: 411001", which
  is a postal code.

A check written as a pattern misses what it does not describe: a password in
a sentence with no label, a key with no known prefix and no label, a number
split across two passages. This lowers what reaches the assistant; it does not
promise that nothing sensitive ever does.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, cast

HIDDEN_NOTE = (
    "Some values in this result are hidden by sextant: card numbers, CVVs, "
    "passwords, PINs, one-time codes, keys and tokens, and identity or bank "
    "account numbers never reach the assistant. Do not guess them. Tell the "
    "user which file and page holds the value, so they can open it on their "
    "own computer; no tool and no request can show it here."
)


def _marker(kind: str) -> str:
    return f"[hidden: {kind}]"


# --- checksums -------------------------------------------------------------


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def _verhoeff(digits: str) -> bool:
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][int(ch)]]
    return check == 0


# --- patterns that stand on their own --------------------------------------

_ANYWHERE: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
        ),
    ),
    ("key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}")),
    ("key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    (
        "token",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    ),
)

# `scheme://user:password@host`: the password goes, the rest stays readable.
_URL_PASSWORD = re.compile(r"(?P<head>\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:)[^\s@/]+(?=@)", re.I)

# --- patterns that need their label in front ------------------------------

# "no", "number", "#", then ":" or "=" or "is" -- any of them, or none.
_LOOSE = r"(?P<sep>[ \t]*(?:(?:no|num|number)\.?[ \t]*)?(?:[:#=\-]|\bis\b)?[ \t]*)"
# Words whose value follows them in ordinary prose ("password reset link")
# need a real separator before anything counts as the value.
_STRICT = r"(?P<sep>[ \t]*(?:[:=]|\bis\b)[ \t]*)"
# "is" alone is ordinary prose ("the password is required"): after it, only a
# value with a digit or a symbol in it counts as a password.
_AFTER_IS = r"(?P<sep>[ \t]+is[ \t]+)"
_SYMBOLIC = r"(?=[^\s\[]*[0-9!@#$%^&*_+=~])[^\s\[]\S{3,}"
_NOT_DONE = r"(?!\[hidden)"

_LABELLED: tuple[tuple[str, str, str, str], ...] = (
    # kind, label, separator, value
    (
        "CVV",
        r"cvv2?|cvc2?|card\s+verification\s+(?:value|code)|security\s+code",
        _LOOSE,
        r"\d{3,4}(?!\d)",
    ),
    (
        "PIN",
        r"m-?pin|atm\s+pin|upi\s+pin|card\s+pin|login\s+pin|secret\s+pin|pin\s+number",
        _LOOSE,
        r"\d{4,6}(?!\d)",
    ),
    ("one-time code", r"otp|one[\s-]time\s+(?:password|code)", _LOOSE, r"\d{4,8}(?!\d)"),
    (
        "card number",
        r"(?:credit|debit|atm)?\s*card\s+(?:no|num|number)\.?",
        r"(?P<sep>[ \t]*[:#=\-]?[ \t]*)",
        r"\d(?:[ \-]?\d){12,18}(?!\d)",
    ),
    (
        "Aadhaar number",
        r"aadhaa?r|uidai|uid|vid|virtual\s+id",
        _LOOSE,
        r"\d{4}[ \-]?\d{4}[ \-]?\d{4}(?:[ \-]?\d{4})?(?!\d)",
    ),
    ("PAN", r"pan|permanent\s+account\s+number", _LOOSE, r"[A-Z]{5}\d{4}[A-Z](?![A-Z0-9])"),
    ("passport number", r"passport", _LOOSE, r"(?=[A-Z0-9]*\d)[A-Z0-9]{6,9}(?![A-Z0-9])"),
    ("voter ID", r"voter\s*id|epic", _LOOSE, r"[A-Z]{3}\d{7}(?!\d)"),
    (
        "driving licence number",
        r"driving\s+licen[cs]e|licen[cs]e|dl",
        _LOOSE,
        r"[A-Z]{2}[ \-]?\d{2}[ \-]?\d{4}[ \-]?\d{7}(?!\d)",
    ),
    (
        "bank account number",
        r"(?:bank\s+|savings\s+|current\s+)?(?:account|a/c|acct)",
        _LOOSE,
        r"\d(?:[ \-]?\d){8,17}(?!\d)",
    ),
    (
        "password",
        r"password|passwd|passcode|passphrase|pwd",
        r"(?P<sep>[ \t]*[:=][ \t]*)",
        r"[^\s\[]\S{3,}",
    ),
    ("password", r"password|passwd|passcode|passphrase", _AFTER_IS, _SYMBOLIC),
    (
        "key",
        r"api[\s_\-]?key|secret(?:[\s_\-]?key)?|access[\s_\-]?key(?:[\s_\-]?id)?"
        r"|client[\s_\-]?secret|private[\s_\-]?key|(?:auth|access|bearer|refresh)?[\s_\-]?token",
        _STRICT,
        r"[A-Za-z0-9_\-./+=]{12,}",
    ),
)

_LABELLED_RE: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        kind,
        re.compile(rf"(?P<label>\b(?:{label}))(?![a-z]){sep}{_NOT_DONE}(?P<value>{value})", re.I),
    )
    for kind, label, sep, value in _LABELLED
)

# --- checksum-backed numbers with no label ---------------------------------

_CARD = re.compile(r"(?<![\d\-])[2-6]\d{3}(?:[ \-]?\d){9,15}(?![\d\-])")
_AADHAAR = re.compile(r"(?<![\d\-])[2-9]\d{3}([ \-]?)\d{4}\1\d{4}(?![\d\-])")
_PAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z](?![A-Za-z0-9])")


def text(value: str) -> tuple[str, Counter[str]]:
    """`value` with every secret it holds replaced, and a count of each kind."""
    hidden: Counter[str] = Counter()

    def sub(pattern: re.Pattern[str], kind: str, s: str) -> str:
        def one(_m: re.Match[str]) -> str:
            hidden[kind] += 1
            return _marker(kind)

        return pattern.sub(one, s)

    out = value
    for kind, pattern in _ANYWHERE:
        out = sub(pattern, kind, out)

    def url(m: re.Match[str]) -> str:
        hidden["password"] += 1
        return m.group("head") + _marker("password")

    out = _URL_PASSWORD.sub(url, out)

    for kind, pattern in _LABELLED_RE:

        def labelled(m: re.Match[str], kind: str = kind) -> str:
            hidden[kind] += 1
            return m.group("label") + m.group("sep") + _marker(kind)

        out = pattern.sub(labelled, out)

    def checked(kind: str, check: Any) -> Any:
        def one(m: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", m.group(0))
            if not check(digits) or len(set(digits)) == 1:
                return m.group(0)
            hidden[kind] += 1
            return _marker(kind)

        return one

    out = _CARD.sub(checked("card number", lambda d: 13 <= len(d) <= 19 and _luhn(d)), out)
    out = _AADHAAR.sub(checked("Aadhaar number", _verhoeff), out)
    out = sub(_PAN, "PAN", out)
    return out, hidden


def walk(value: Any) -> tuple[Any, Counter[str]]:
    """`value` with every string inside it passed through `text`. Keys stay."""
    if isinstance(value, str):
        return text(value)
    hidden: Counter[str] = Counter()
    if isinstance(value, dict):
        out_dict: dict[Any, Any] = {}
        for k, v in value.items():
            out_dict[k], found = walk(v)
            hidden.update(found)
        return out_dict, hidden
    if isinstance(value, (list, tuple)):
        items = []
        for v in value:
            item, found = walk(v)
            items.append(item)
            hidden.update(found)
        return (type(value)(items) if isinstance(value, tuple) else items), hidden
    return value, hidden


def result(value: dict[str, Any]) -> dict[str, Any]:
    """A tool result as it may leave this server: secrets hidden, and said so."""
    out, hidden = walk(value)
    if hidden:
        out["hidden"] = dict(sorted(hidden.items()))
        out["hidden_note"] = HIDDEN_NOTE
    return cast(dict[str, Any], out)
