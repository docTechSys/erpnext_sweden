"""
Unit tests for the BgMax parser.

BgMax files use ISO-8859-1 encoding and 80-character fixed-width records.
All test fixtures are minimal but structurally valid files with correct
amounts, dates, and record counts.
"""

import unittest
from datetime import date
from decimal import Decimal

from erpnext_sweden.parsers import bgmax


# ---------------------------------------------------------------------------
# Fixtures — proper fixed-width field builders
# ---------------------------------------------------------------------------

def _rec(content: str) -> bytes:
    """Pad to exactly 80 chars and encode as ISO-8859-1."""
    return content.ljust(80).encode("iso-8859-1")


def _bgmax_file(*records: str) -> bytes:
    """Join records with CRLF (canonical BgMax) then a trailing CRLF."""
    return b"\r\n".join(_rec(r) for r in records) + b"\r\n"


def _tc00(date8: str = "20240115", time6: str = "120000", prod: bool = True) -> str:
    flag = "P" if prod else "T"
    return f"00BGMAX     01      {date8}{time6}{flag}"


def _tc05(bg: str, currency: str = "SEK") -> str:
    return "05" + bg.rjust(10) + currency.ljust(10)


def _tc15(sender_bg: str, ocr: str, amount_ore: int, date8: str, channel: str = "1") -> str:
    return "15" + sender_bg.rjust(10) + ocr.rjust(25) + str(amount_ore).rjust(15) + date8 + channel


def _tc20(sender_bg: str, ref: str, amount_ore: int, date8: str, channel: str = "4", name: str = "") -> str:
    return "20" + sender_bg.rjust(10) + ref.ljust(25) + str(amount_ore).rjust(15) + date8 + channel + name


def _tc25(text: str) -> str:
    return "25" + text[:75].ljust(75)


def _tc26(bg: str, amount_ore: int, date8: str) -> str:
    return "26" + bg.rjust(10) + str(amount_ore).rjust(15) + date8


def _tc65(bg: str, credit_count: int, total_ore: int, text_count: int = 0) -> str:
    return "65" + bg.rjust(10) + str(credit_count).rjust(15) + str(total_ore).rjust(15) + str(text_count).rjust(15)


def _tc99(sections: int = 1, tc15_count: int = 0, tc20_count: int = 0, tc25_count: int = 0, tc26_count: int = 0) -> str:
    return "99" + str(sections).rjust(15) + str(tc15_count).rjust(15) + str(tc20_count).rjust(15) + str(tc25_count).rjust(15) + str(tc26_count).rjust(15)


# Minimal valid BgMax with one TC05 section containing two TC15 payments
_MINIMAL_BGMAX = _bgmax_file(
    _tc00(),
    _tc05("1234567"),
    _tc15("3456789", "1234566", 15000, "20240110"),
    _tc15("3456789", "9876549", 25000, "20240112"),
    _tc65("1234567", 2, 40000),
    _tc99(sections=1, tc15_count=2),
)

# BgMax with TC20 (free-text reference) and TC25 (continuation text)
_BGMAX_WITH_TC20 = _bgmax_file(
    _tc00(),
    _tc05("7956253"),
    _tc20("3456789", "INV-2024-001", 5000, "20240113", name="Supplier AB"),
    _tc25("Faktura 2024-001 extra info"),
    _tc65("7956253", 1, 5000, text_count=1),
    _tc99(sections=1, tc20_count=1, tc25_count=1),
)

# BgMax with TC26 debit (reversal)
_BGMAX_WITH_DEBIT = _bgmax_file(
    _tc00(),
    _tc05("1234567"),
    _tc15("3456789", "1234566", 1000, "20240110"),
    _tc26("1234567", 500, "20240111"),
    _tc65("1234567", 1, 1000),
    _tc99(sections=1, tc15_count=1, tc26_count=1),
)

# BgMax with multiple TC05 sections (two BG accounts in one file)
_BGMAX_MULTI_SECTION = _bgmax_file(
    _tc00(),
    _tc05("1111111"),
    _tc15("2222222", "1234566", 1000, "20240110"),
    _tc65("1111111", 1, 1000),
    _tc05("3333333"),
    _tc15("4444444", "9876549", 2000, "20240111"),
    _tc65("3333333", 1, 2000),
    _tc99(sections=2, tc15_count=2),
)

# Test mode indicator
_BGMAX_TEST_MODE = _bgmax_file(
    _tc00(prod=False),
    _tc05("1234567"),
    _tc99(sections=1),
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBgMaxDetection(unittest.TestCase):
    def test_detects_bgmax(self):
        self.assertTrue(bgmax.is_bgmax(_MINIMAL_BGMAX))

    def test_rejects_xml(self):
        xml = b'<?xml version="1.0"?><Document/>'
        self.assertFalse(bgmax.is_bgmax(xml))

    def test_rejects_empty(self):
        self.assertFalse(bgmax.is_bgmax(b""))

    def test_rejects_random_text(self):
        self.assertFalse(bgmax.is_bgmax(b"Hello world\nThis is not a bank file\n"))


class TestBgMaxMinimal(unittest.TestCase):
    def setUp(self):
        self.stmts = bgmax.parse(_MINIMAL_BGMAX)

    def test_returns_one_statement(self):
        self.assertEqual(len(self.stmts), 1)

    def test_account_id(self):
        stmt = self.stmts[0]
        self.assertEqual(stmt.other_account_id, "1234567")
        self.assertEqual(stmt.other_account_issuer, "BG")

    def test_currency(self):
        self.assertEqual(self.stmts[0].currency, "SEK")

    def test_transaction_count(self):
        self.assertEqual(len(self.stmts[0].transactions), 2)

    def test_first_transaction_amount(self):
        tx = self.stmts[0].transactions[0]
        self.assertEqual(tx.amount, Decimal("150.00"))
        self.assertEqual(tx.currency, "SEK")
        self.assertEqual(tx.credit_debit, "CRDT")

    def test_second_transaction_amount(self):
        tx = self.stmts[0].transactions[1]
        self.assertEqual(tx.amount, Decimal("250.00"))

    def test_transaction_dates(self):
        txs = self.stmts[0].transactions
        self.assertEqual(txs[0].booking_date, date(2024, 1, 10))
        self.assertEqual(txs[1].booking_date, date(2024, 1, 12))

    def test_ocr_reference(self):
        tx = self.stmts[0].transactions[0]
        self.assertEqual(tx.structured_ref, "1234566")

    def test_sender_bg(self):
        tx = self.stmts[0].transactions[0]
        self.assertEqual(tx.party_account_number, "3456789")

    def test_status_is_book(self):
        self.assertEqual(self.stmts[0].transactions[0].status, "BOOK")

    def test_closing_balance(self):
        # Sum of 150 + 250 = 400
        cb = self.stmts[0].closing_balance
        self.assertEqual(cb, Decimal("400.00"))

    def test_file_date_in_creation(self):
        stmt = self.stmts[0]
        self.assertIsNotNone(stmt.creation_datetime)
        self.assertEqual(stmt.creation_datetime.date(), date(2024, 1, 15))


class TestBgMaxWithTC20(unittest.TestCase):
    def setUp(self):
        self.stmt = bgmax.parse(_BGMAX_WITH_TC20)[0]

    def test_tc20_amount(self):
        self.assertEqual(len(self.stmt.transactions), 1)
        self.assertEqual(self.stmt.transactions[0].amount, Decimal("50.00"))

    def test_tc20_party_name(self):
        self.assertEqual(self.stmt.transactions[0].party_name, "Supplier AB")

    def test_tc20_free_ref(self):
        self.assertEqual(self.stmt.transactions[0].unstructured_ref, "INV-2024-001")

    def test_tc25_appended_to_description(self):
        desc = self.stmt.transactions[0].description
        self.assertIn("Faktura 2024-001", desc)

    def test_tc20_no_structured_ref(self):
        self.assertEqual(self.stmt.transactions[0].structured_ref, "")


class TestBgMaxWithDebit(unittest.TestCase):
    def setUp(self):
        self.stmt = bgmax.parse(_BGMAX_WITH_DEBIT)[0]

    def test_has_credit_and_debit(self):
        txs = self.stmt.transactions
        self.assertEqual(len(txs), 2)
        cds = {tx.credit_debit for tx in txs}
        self.assertIn("CRDT", cds)
        self.assertIn("DBIT", cds)

    def test_debit_amount(self):
        debit = next(tx for tx in self.stmt.transactions if tx.credit_debit == "DBIT")
        self.assertEqual(debit.amount, Decimal("5.00"))

    def test_net_balance(self):
        # credit 10.00 - debit 5.00 = 5.00
        self.assertEqual(self.stmt.closing_balance, Decimal("5.00"))


class TestBgMaxMultiSection(unittest.TestCase):
    def setUp(self):
        self.stmts = bgmax.parse(_BGMAX_MULTI_SECTION)

    def test_two_statements(self):
        self.assertEqual(len(self.stmts), 2)

    def test_first_bg(self):
        self.assertEqual(self.stmts[0].other_account_id, "1111111")

    def test_second_bg(self):
        self.assertEqual(self.stmts[1].other_account_id, "3333333")

    def test_independent_transactions(self):
        self.assertEqual(len(self.stmts[0].transactions), 1)
        self.assertEqual(len(self.stmts[1].transactions), 1)


class TestBgMaxErrors(unittest.TestCase):
    def test_invalid_file_raises(self):
        with self.assertRaises(ValueError):
            bgmax.parse(b"This is not BgMax at all\n")

    def test_crlf_and_lf_both_work(self):
        lf_version = _MINIMAL_BGMAX.replace(b"\r\n", b"\n")
        stmts = bgmax.parse(lf_version)
        self.assertEqual(len(stmts), 1)

    def test_latin1_characters(self):
        # Swedish characters (å ä ö) in TC25 must decode correctly from ISO-8859-1
        file_with_swedish = _bgmax_file(
            _tc00(),
            _tc05("1234567"),
            _tc15("3456789", "1234566", 1000, "20240110"),
            _tc25("Betalning från Åsa Öberg"),
            _tc65("1234567", 1, 1000, text_count=1),
            _tc99(sections=1, tc15_count=1, tc25_count=1),
        )
        stmts = bgmax.parse(file_with_swedish)
        desc = stmts[0].transactions[0].description
        self.assertIn("Åsa Öberg", desc)


class TestBgMaxOreConversion(unittest.TestCase):
    """Verify öre-to-SEK conversion edge cases."""

    def _single_tx_file(self, amount_ore: int) -> bytes:
        return _bgmax_file(
            _tc00(),
            _tc05("1234567"),
            _tc15("3456789", "1234566", amount_ore, "20240110"),
            _tc65("1234567", 1, amount_ore),
            _tc99(sections=1, tc15_count=1),
        )

    def test_zero_ore(self):
        stmt = bgmax.parse(self._single_tx_file(0))[0]
        self.assertEqual(stmt.transactions[0].amount, Decimal("0.00"))

    def test_one_ore(self):
        stmt = bgmax.parse(self._single_tx_file(1))[0]
        self.assertEqual(stmt.transactions[0].amount, Decimal("0.01"))

    def test_large_amount(self):
        # 10 000 000 SEK = 1 000 000 000 öre
        stmt = bgmax.parse(self._single_tx_file(1_000_000_000))[0]
        self.assertEqual(stmt.transactions[0].amount, Decimal("10000000.00"))


if __name__ == "__main__":
    unittest.main()
