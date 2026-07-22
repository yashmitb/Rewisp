"""PII redaction before storage. Precision-first: the tests care as much about
what is LEFT ALONE as what is removed, because over-redaction corrupts real
memories — the failure the user actually feels."""

from rewisp import db, redact


# ── cards ────────────────────────────────────────────────────────────────────

def test_redacts_valid_visa():
    # 4111 1111 1111 1111 is the canonical Luhn-valid Visa test number.
    assert redact.scrub_pii("paid with 4111 1111 1111 1111 today") == "paid with [card] today"


def test_redacts_hyphenated_and_bare_card():
    assert "[card]" in redact.scrub_pii("card 4111-1111-1111-1111 on file")
    assert "[card]" in redact.scrub_pii("number 4111111111111111 charged")


def test_redacts_amex_15_digit():
    # 378282246310005 — Amex test number, Luhn valid, starts with 3.
    assert redact.scrub_pii("amex 378282246310005") == "amex [card]"


def test_leaves_luhn_invalid_number_alone():
    # 16 digits, right shape, but fails Luhn -> not a card, keep it.
    assert redact.scrub_pii("order 4111 1111 1111 1112") == "order 4111 1111 1111 1112"


def test_leaves_long_id_without_card_prefix():
    # Starts with 9 (not a network digit) -> left alone even if long.
    s = "tracking 9999888877776666 shipped"
    assert redact.scrub_pii(s) == s


def test_leaves_phone_and_short_numbers():
    for s in ("call 415-555-0198", "pin 4821", "zip 92093", "year 2026"):
        assert redact.scrub_pii(s) == s


# ── SSNs ─────────────────────────────────────────────────────────────────────

def test_redacts_valid_ssn():
    assert redact.scrub_pii("SSN 123-45-6789 on the form") == "SSN [ssn] on the form"


def test_leaves_invalid_ssn_ranges():
    for s in ("000-12-3456", "666-12-3456", "900-12-3456", "123-00-6789", "123-45-0000"):
        assert redact.scrub_pii(s) == s, s


def test_leaves_ordinary_dashed_numbers():
    # A model number / date-like dashed string is not an SSN shape.
    assert redact.scrub_pii("model 12-3456-7") == "model 12-3456-7"


# ── behaviour ────────────────────────────────────────────────────────────────

def test_idempotent():
    once = redact.scrub_pii("card 4111 1111 1111 1111 ssn 123-45-6789")
    assert redact.scrub_pii(once) == once
    assert "[card]" in once and "[ssn]" in once


def test_empty_and_none_safe():
    assert redact.scrub_pii("") == ""
    assert redact.scrub_pii("nothing sensitive here") == "nothing sensitive here"


def test_insert_capture_never_stores_a_card(conn):
    rid = db.insert_capture(conn, "Mail", None, None,
                            "invoice total charged to 4111 1111 1111 1111 thanks")
    stored = conn.execute("SELECT ocr_text FROM captures WHERE id=?", (rid,)).fetchone()[0]
    assert "4111" not in stored and "[card]" in stored


def test_insert_capture_redaction_respects_flag(conn, monkeypatch):
    from rewisp import config
    monkeypatch.setattr(config, "REDACT_PII", False)
    rid = db.insert_capture(conn, "Mail", None, None, "num 4111 1111 1111 1111")
    stored = conn.execute("SELECT ocr_text FROM captures WHERE id=?", (rid,)).fetchone()[0]
    assert "4111 1111 1111 1111" in stored     # off -> untouched
