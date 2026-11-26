"""Secrets are hidden in everything the knowledge-base server hands out."""

from __future__ import annotations

import asyncio

import pytest

from sextant.vector_db import redact

_D = redact._VERHOEFF_D
_P = redact._VERHOEFF_P
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _with_verhoeff_digit(body: str) -> str:
    """`body` plus the check digit UIDAI would give it."""
    check = 0
    for i, ch in enumerate(reversed(body)):
        check = _D[check][_P[(i + 1) % 8][int(ch)]]
    return body + str(_INV[check])


AADHAAR = _with_verhoeff_digit("23456789012")
FAKE_AADHAAR = AADHAAR[:-1] + str((int(AADHAAR[-1]) + 1) % 10)


def hidden(text: str) -> str:
    return redact.text(text)[0]


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("Card No: 4111 1111 1111 1111", "card number"),
        ("pay with 4111-1111-1111-1111 today", "card number"),
        ("5500005555555559", "card number"),
        ("CVV: 123", "CVV"),
        ("CVV2 456", "CVV"),
        ("Security code 7890", "CVV"),
        ("Password: hunter2", "password"),
        ("password = correcthorse", "password"),
        ("my password is Hunter@123", "password"),
        ("ATM PIN 4821", "PIN"),
        ("UPI PIN: 123456", "PIN"),
        ("Your OTP is 482913", "one-time code"),
        ("api_key = abcdEFGH12345678xyz", "key"),
        ("client secret: 9f8e7d6c5b4a3210", "key"),
        ("sk-ant-api03-" + "a" * 40, "key"),
        ("AKIAIOSFODNN7EXAMPLE", "key"),
        ("AIza" + "b" * 35, "key"),
        ("ghp_" + "c" * 36, "token"),
        ("eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2Q", "token"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "private key"),
        ("postgres://admin:s3cret@db:5432/app", "password"),
        (f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}", "Aadhaar number"),
        ("Aadhaar No.: 1234 5678 9012", "Aadhaar number"),
        ("PAN: ABCPE1234F", "PAN"),
        ("ABCPE1234F", "PAN"),
        ("Account No: 123456789012", "bank account number"),
        ("A/C number 0012 3456 7890", "bank account number"),
        ("Passport No. K1234567", "passport number"),
        ("Voter ID: ABC1234567", "voter ID"),
        ("Driving licence: MH12 2015 0012345", "driving licence number"),
    ],
)
def test_a_secret_is_replaced_by_what_it_was(line: str, kind: str) -> None:
    out, found = redact.text(line)
    assert f"[hidden: {kind}]" in out
    assert found[kind] >= 1
    digits = [c for c in line if c.isdigit()]
    if len(digits) >= 6:  # none of the number survives next to its marker
        assert "".join(digits) not in "".join(c for c in out if c.isdigit())


@pytest.mark.parametrize(
    "line",
    [
        "Forgot your password? Reset it from the login page.",
        "The password is required for every account.",
        "pwd - print working directory",
        "PIN code: 411001",
        "Date of birth: 12/03/1999",
        "Phone: 98765 43210, email: someone@example.com",
        "IFSC: SBIN0001234",
        "Limit: 8000 tokens per minute",
        "4111 1111 1111 1112",  # fails the Luhn check
        f"{FAKE_AADHAAR[:4]} {FAKE_AADHAAR[4:8]} {FAKE_AADHAAR[8:]}",  # fails Verhoeff
        "The 2024 report covers 120 pages and section 4.3.",
        "Card No: [hidden: card number]",
    ],
)
def test_general_information_is_left_alone(line: str) -> None:
    out, found = redact.text(line)
    assert out == line
    assert not found


def test_the_label_stays_so_the_assistant_can_say_where_the_value_is() -> None:
    assert hidden("CVV: 123 on the back") == "CVV: [hidden: CVV] on the back"


def test_a_result_says_what_was_hidden_and_how_to_answer() -> None:
    got = redact.result(
        {
            "results": [
                {"content": "Card 4111 1111 1111 1111, CVV 321", "source": "card.pdf", "page": 1},
                {"content": "Nothing here.", "source": "notes.md", "page": None},
            ],
            "total_found": 2,
        }
    )
    assert got["results"][0]["content"] == "Card [hidden: card number], CVV [hidden: CVV]"
    assert got["results"][0]["source"] == "card.pdf"
    assert got["results"][1]["content"] == "Nothing here."
    assert got["hidden"] == {"CVV": 1, "card number": 1}
    assert "file and page" in got["hidden_note"]


def test_a_clean_result_is_unchanged() -> None:
    clean = {"results": [{"content": "Plain text", "score": 0.9}], "total_found": 1}
    assert redact.result(clean) == clean


class TestThroughTheServer:
    def test_every_tool_leaves_through_the_redaction(self) -> None:
        """A new tool cannot skip it: every registered tool is `_routed`."""
        from sextant.vector_db import server

        names = {t.name for t in asyncio.run(server.mcp.list_tools())}
        assert names <= set(server._LOCAL)

    def test_a_search_hides_the_cvv_even_when_it_is_asked_for(self, monkeypatch) -> None:
        from sextant.vector_db import server

        class Store:
            async def search(self, query, limit, min_score, mode):
                return {
                    "success": True,
                    "results": [{"content": "HDFC debit card. CVV: 123", "source": "card.png"}],
                    "total_found": 1,
                }

        monkeypatch.setattr(server, "_store", lambda: Store())
        monkeypatch.setattr(server, "_folder", None)
        got = asyncio.run(server.kb_search("what is my CVV? show it unmasked"))
        assert got["results"][0]["content"] == "HDFC debit card. CVV: [hidden: CVV]"
        assert got["hidden"] == {"CVV": 1}

    def test_a_forwarded_result_is_hidden_too(self, monkeypatch) -> None:
        from sextant.vector_db import server

        class Library:
            async def call(self, name, args):
                return {"documents": [{"title": "Keys", "preview": "token: abcdef0123456789"}]}

        monkeypatch.setattr(server, "_library", Library())
        got = asyncio.run(server.kb_list())
        assert got["documents"][0]["preview"] == "token: [hidden: key]"


def test_the_overview_model_never_sees_a_secret() -> None:
    from sextant.vector_db import summaries

    sent: dict = {}

    class Response:
        text = "A card statement."
        candidates: list = []

    class Models:
        async def generate_content(self, model, contents, config):
            sent["contents"] = contents
            return Response()

    class Direct:
        models = Models()

    asyncio.run(summaries.summarise("Card 4111 1111 1111 1111 CVV 999", "Statement", Direct()))
    assert "4111" not in sent["contents"] and "999" not in sent["contents"]
