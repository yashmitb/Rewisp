"""Purge high-confidence PII from captured screen text before it is stored.

Rewisp's kill list already pauses capture on banking sites, password managers and
private windows — the surfaces where card and identity numbers are the whole
point. This is the backstop for the ones that leak onto otherwise-ordinary
screens: an order confirmation showing a card, an email quoting an SSN, a form
you half-filled. Those numbers have no value as memory and every value as
liability, so they never reach the database or the embedding.

Precision-first, because redaction destroys data: only patterns we can validate
are touched.

- **Card numbers**: 13–19 digits that pass the Luhn checksum and begin with a
  real card-network digit (3/4/5/6). Random long numbers rarely satisfy all
  three, so order ids and phone numbers survive.
- **SSNs**: the dashed XXX-XX-XXXX form only (bare 9-digit runs are too ambiguous
  to redact safely), excluding the ranges the SSA never issues.

Everything else is deliberately left alone — over-redaction corrupts real
memories, which is the failure the user actually feels.
"""

import re

# A run of 13–19 digits, optionally grouped by single spaces or hyphens
# ("4532 1488 0343 6467"). Bounded so it won't span across unrelated numbers.
_CARD_CAND = re.compile(r"(?<![\w-])(\d[ -]?){12,18}\d(?![\w-])")

# Dashed SSN. Same shape vault.py refuses at ingest, kept consistent.
_SSN = re.compile(r"(?<!\d)(\d{3})-(\d{2})-(\d{4})(?!\d)")


def _luhn_ok(digits: str) -> bool:
    """Standard Luhn checksum over a string of digits."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_card(digits: str) -> bool:
    return (13 <= len(digits) <= 19
            and digits[0] in "3456"      # Amex/Visa/Mastercard/Discover network digit
            and _luhn_ok(digits))


def _valid_ssn(area: str, group: str, serial: str) -> bool:
    if area in ("000", "666") or area[0] == "9":   # never-issued areas
        return False
    return group != "00" and serial != "0000"


def scrub_pii(text: str) -> str:
    """Replace validated card numbers and SSNs with a placeholder that preserves
    the surrounding memory ('paid with [card]'). Idempotent; safe to call on text
    that was already scrubbed. Returns the text unchanged when nothing matches."""
    if not text:
        return text

    def card_sub(m: re.Match) -> str:
        digits = re.sub(r"[ -]", "", m.group(0))
        return "[card]" if _is_card(digits) else m.group(0)

    def ssn_sub(m: re.Match) -> str:
        return "[ssn]" if _valid_ssn(m.group(1), m.group(2), m.group(3)) else m.group(0)

    text = _CARD_CAND.sub(card_sub, text)
    text = _SSN.sub(ssn_sub, text)
    return text
