"""
BgMax (Bankgiro Inbetalningar) fixed-width file parser.

BgMax is Bankgirot's proprietary format for incoming Bankgiro payments.
It is being phased out in favour of camt.053/054 — final deadline 27 Nov 2026.

File characteristics:
  - Encoding: ISO-8859-1 (Latin-1)
  - Record length: exactly 80 characters per line
  - Line endings: CR+LF (Windows) or LF (Unix)
  - Amounts: integer öre (1 SEK = 100 öre)

Record types (TC = Transaction Code):
  TC00  Opening record (file header)
  TC05  Bankgiro section header (one per recipient BG account)
  TC15  Deposit with OCR reference
  TC20  Deposit with free-text reference or name
  TC25  Free text (continuation of preceding TC15/TC20)
  TC26  Debit (auto-debit/reversal)
  TC65  Section total (credits)
  TC70  Section total (debits)
  TC99  Closing record (file trailer)

The parser returns ParsedStatement objects identical in shape to those
produced by the camt.053 parser, so the import doctype handles both
formats without branching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from erpnext_sweden.parsers.camt053 import ParsedBalance, ParsedStatement, ParsedTransaction


# ---------------------------------------------------------------------------
# Internal record dataclasses
# ---------------------------------------------------------------------------


@dataclass
class _TC00:
    file_date: date
    file_time: str
    test: bool


@dataclass
class _TC05:
    bg_number: str
    currency: str


@dataclass
class _TC15:
    sender_bg: str
    ocr_reference: str
    amount_ore: int
    payment_date: date
    channel: str


@dataclass
class _TC20:
    sender_bg: str
    free_ref: str
    amount_ore: int
    payment_date: date
    channel: str
    sender_name: str


@dataclass
class _TC25:
    text: str


@dataclass
class _TC26:
    bg_number: str
    amount_ore: int
    debit_date: date


@dataclass
class _TC65:
    bg_number: str
    credit_count: int
    credit_total_ore: int


@dataclass
class _TC70:
    bg_number: str
    debit_count: int
    debit_total_ore: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHANNEL_LABELS: dict[str, str] = {
    "1": "Bankgiro",
    "4": "Internet Banking",
    "5": "Manual Entry",
    "9": "Other",
}


def _parse_date8(s: str) -> date | None:
    """Parse an 8-character YYYYMMDD string into a date, or None."""
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _ore_to_decimal(ore: int) -> Decimal:
    """Convert integer öre to SEK Decimal."""
    return Decimal(ore) / 100


def _strip(s: str) -> str:
    return s.strip()


# ---------------------------------------------------------------------------
# Record parsers (each expects exactly 80 chars, no trailing newline)
# ---------------------------------------------------------------------------


def _parse_tc00(rec: str) -> _TC00:
    file_date = _parse_date8(rec[20:28]) or date.today()
    return _TC00(
        file_date=file_date,
        file_time=rec[28:34].strip(),
        test=rec[34:35].upper() == "T",
    )


def _parse_tc05(rec: str) -> _TC05:
    return _TC05(
        bg_number=_strip(rec[2:12]),
        currency=_strip(rec[12:15]) or "SEK",
    )


def _parse_tc15(rec: str) -> _TC15:
    return _TC15(
        sender_bg=_strip(rec[2:12]),
        ocr_reference=_strip(rec[12:37]),
        amount_ore=int(_strip(rec[37:52]) or "0"),
        payment_date=_parse_date8(rec[52:60]) or date.today(),
        channel=rec[60:61],
    )


def _parse_tc20(rec: str) -> _TC20:
    return _TC20(
        sender_bg=_strip(rec[2:12]),
        free_ref=_strip(rec[12:37]),
        amount_ore=int(_strip(rec[37:52]) or "0"),
        payment_date=_parse_date8(rec[52:60]) or date.today(),
        channel=rec[60:61],
        sender_name=_strip(rec[61:80]),  # remainder of record after channel
    )


def _parse_tc25(rec: str) -> _TC25:
    return _TC25(text=_strip(rec[2:77]))


def _parse_tc26(rec: str) -> _TC26:
    return _TC26(
        bg_number=_strip(rec[2:12]),
        amount_ore=int(_strip(rec[12:27]) or "0"),
        debit_date=_parse_date8(rec[27:35]) or date.today(),
    )


def _parse_tc65(rec: str) -> _TC65:
    return _TC65(
        bg_number=_strip(rec[2:12]),
        credit_count=int(_strip(rec[12:27]) or "0"),
        credit_total_ore=int(_strip(rec[27:42]) or "0"),
    )


def _parse_tc70(rec: str) -> _TC70:
    return _TC70(
        bg_number=_strip(rec[2:12]),
        debit_count=int(_strip(rec[12:27]) or "0"),
        debit_total_ore=int(_strip(rec[27:42]) or "0"),
    )


_TC_PARSERS = {
    "00": _parse_tc00,
    "05": _parse_tc05,
    "15": _parse_tc15,
    "20": _parse_tc20,
    "25": _parse_tc25,
    "26": _parse_tc26,
    "65": _parse_tc65,
    "70": _parse_tc70,
}


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------


def _build_statement(tc05: _TC05, payment_records: list, debit_records: list[_TC26]) -> ParsedStatement:
    """Convert a TC05 section into a ParsedStatement."""
    ps = ParsedStatement(
        other_account_id=tc05.bg_number,
        other_account_issuer="BG",
        currency=tc05.currency,
        bank_name="Bankgirot",
    )

    credit_total = Decimal(0)
    debit_total = Decimal(0)

    for item in payment_records:
        if isinstance(item, (_TC15, _TC20)):
            amount = _ore_to_decimal(item.amount_ore)
            credit_total += amount

            if isinstance(item, _TC15):
                ref = item.ocr_reference
                desc = ""
                channel_label = _CHANNEL_LABELS.get(item.channel, "Bankgiro")
                party_bg = item.sender_bg
                party_name = ""
            else:  # TC20
                ref = item.free_ref
                desc = item.free_ref
                channel_label = _CHANNEL_LABELS.get(item.channel, "Bankgiro")
                party_bg = item.sender_bg
                party_name = item.sender_name

            tx = ParsedTransaction(
                amount=amount,
                currency=tc05.currency,
                credit_debit="CRDT",
                status="BOOK",
                booking_date=item.payment_date,
                value_date=item.payment_date,
                structured_ref=ref if isinstance(item, _TC15) else "",
                unstructured_ref=desc,
                party_name=party_name,
                party_account_number=party_bg,
                description=f"{channel_label}: {ref or party_name or ''}".strip(": "),
                transaction_type=channel_label,
            )
            ps.transactions.append(tx)

        elif isinstance(item, _TC25) and ps.transactions:
            # Append free-text to the preceding transaction's description
            last = ps.transactions[-1]
            extra = item.text
            if extra:
                last.description = f"{last.description} | {extra}".strip(" |")
                if not last.unstructured_ref:
                    last.unstructured_ref = extra

    for dr in debit_records:
        amount = _ore_to_decimal(dr.amount_ore)
        debit_total += amount
        ps.transactions.append(
            ParsedTransaction(
                amount=amount,
                currency=tc05.currency,
                credit_debit="DBIT",
                status="BOOK",
                booking_date=dr.debit_date,
                value_date=dr.debit_date,
                description="Bankgiro debit / reversal",
                transaction_type="Debit",
            )
        )

    # Synthesise approximate balances from totals (BgMax doesn't carry balances)
    if credit_total or debit_total:
        ps.balances.append(ParsedBalance(
            type_code="CLBD",
            amount=credit_total - debit_total,
            currency=tc05.currency,
            credit_debit="CRDT" if credit_total >= debit_total else "DBIT",
        ))

    return ps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_bgmax(data: bytes) -> bool:
    """Return True if the byte content looks like a BgMax file."""
    try:
        first_line = data.split(b"\n")[0].rstrip(b"\r")
        return first_line[:2] == b"00" and b"BGMAX" in first_line[:15]
    except Exception:
        return False


def parse(data: bytes) -> list[ParsedStatement]:
    """
    Parse a BgMax file and return one ParsedStatement per TC05 section.

    BgMax files are ISO-8859-1 encoded. The parser accepts both CR+LF and
    LF line endings and is lenient about trailing whitespace.

    Raises ValueError for files that are not recognisable BgMax.
    """
    try:
        text = data.decode("iso-8859-1")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")

    lines = [line.rstrip("\r") for line in text.splitlines()]

    if not lines or not lines[0].startswith("00"):
        raise ValueError("Not a valid BgMax file: first record must be TC00")

    # Pad short lines to 80 chars so positional slicing is always safe
    records = [line.ljust(80) for line in lines if line.strip()]

    tc00: _TC00 | None = None
    statements: list[ParsedStatement] = []

    current_tc05: _TC05 | None = None
    current_payments: list = []   # _TC15 | _TC20 | _TC25
    current_debits: list[_TC26] = []

    for rec in records:
        tc = rec[0:2]
        handler = _TC_PARSERS.get(tc)

        if tc == "00":
            tc00 = _parse_tc00(rec)

        elif tc == "05":
            if current_tc05 is not None:
                statements.append(_build_statement(current_tc05, current_payments, current_debits))
            current_tc05 = _parse_tc05(rec)
            current_payments = []
            current_debits = []

        elif tc in ("15", "20", "25"):
            if handler:
                current_payments.append(handler(rec))

        elif tc == "26":
            current_debits.append(_parse_tc26(rec))

        elif tc in ("65", "70", "99"):
            pass  # Totals — used for validation only, not re-implemented here

    # Flush last section
    if current_tc05 is not None:
        statements.append(_build_statement(current_tc05, current_payments, current_debits))

    if tc00 and tc00.file_date:
        for stmt in statements:
            if stmt.creation_datetime is None:
                stmt.creation_datetime = datetime.combine(tc00.file_date, datetime.min.time())

    return statements
