"""
Unit tests for the camt.053 parser, utilities, and bank profiles.
These tests use only stdlib — no Frappe context required.
"""

import unittest
from datetime import date
from decimal import Decimal
from textwrap import dedent

from erpnext_sweden.parsers import camt053
from erpnext_sweden.parsers.bank_profiles import get_profile, HANDELSBANKEN, NORDEA, SEB
from erpnext_sweden.utils.ocr import validate_ocr, normalize_ocr
from erpnext_sweden.utils.swedish_iban import (
    validate_se_iban,
    iban_to_clearing_account,
    clearing_account_to_iban,
    clearing_to_bank_name,
)
from erpnext_sweden.utils.bankgiro import normalize_bankgiro, format_bankgiro, normalize_plusgiro


# ---------------------------------------------------------------------------
# Minimal valid camt.053.001.02 XML fixture
# ---------------------------------------------------------------------------

_CAMT053_V2_XML = dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
      <BkToCstmrStmt>
        <GrpHdr>
          <MsgId>MSG-20240115-001</MsgId>
          <CreDtTm>2024-01-15T08:00:00</CreDtTm>
        </GrpHdr>
        <Stmt>
          <Id>STMT-001</Id>
          <FrToDt>
            <FrDtTm>2024-01-01T00:00:00</FrDtTm>
            <ToDtTm>2024-01-15T23:59:59</ToDtTm>
          </FrToDt>
          <Acct>
            <Id><IBAN>SE4550000000058398257466</IBAN></Id>
            <Ccy>SEK</Ccy>
            <Nm>Test Company AB</Nm>
            <Svcr>
              <FinInstnId>
                <BIC>HANDSESS</BIC>
                <Nm>Handelsbanken</Nm>
              </FinInstnId>
            </Svcr>
          </Acct>
          <Bal>
            <Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp>
            <Amt Ccy="SEK">100000.00</Amt>
            <CdtDbtInd>CRDT</CdtDbtInd>
            <Dt><Dt>2024-01-01</Dt></Dt>
          </Bal>
          <Bal>
            <Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp>
            <Amt Ccy="SEK">115000.00</Amt>
            <CdtDbtInd>CRDT</CdtDbtInd>
            <Dt><Dt>2024-01-15</Dt></Dt>
          </Bal>
          <Ntry>
            <Amt Ccy="SEK">15000.00</Amt>
            <CdtDbtInd>CRDT</CdtDbtInd>
            <Sts>BOOK</Sts>
            <BookgDt><Dt>2024-01-10</Dt></BookgDt>
            <ValDt><Dt>2024-01-10</Dt></ValDt>
            <AcctSvcrRef>SVC-REF-001</AcctSvcrRef>
            <BkTxCd>
              <Domn><Cd>PMNT</Cd><Fmly><Cd>RCDT</Cd><SubFmlyCd>VCOM</SubFmlyCd></Fmly></Domn>
              <Prtry><Cd>K04</Cd></Prtry>
            </BkTxCd>
            <AddtlNtryInf>Invoice payment</AddtlNtryInf>
            <NtryDtls>
              <TxDtls>
                <Refs><EndToEndId>E2E-001</EndToEndId></Refs>
                <RltdPties>
                  <Dbtr><Nm>Customer AB</Nm></Dbtr>
                  <DbtrAcct><Id><IBAN>SE7280000810340009783242</IBAN></Id></DbtrAcct>
                </RltdPties>
                <RmtInf>
                  <Strd>
                    <CdtrRefInf><Ref>1234566</Ref></CdtrRefInf>
                  </Strd>
                </RmtInf>
              </TxDtls>
            </NtryDtls>
          </Ntry>
        </Stmt>
      </BkToCstmrStmt>
    </Document>
""").encode()

_CAMT053_V8_XML = _CAMT053_V2_XML.replace(
    b"urn:iso:std:iso:20022:tech:xsd:camt.053.001.02",
    b"urn:iso:std:iso:20022:tech:xsd:camt.053.001.08",
)


class TestCamt053Parser(unittest.TestCase):
    def test_parse_v2(self):
        stmts = camt053.parse(_CAMT053_V2_XML)
        self.assertEqual(len(stmts), 1)
        stmt = stmts[0]
        self.assertEqual(stmt.message_id, "MSG-20240115-001")
        self.assertEqual(stmt.iban, "SE4550000000058398257466")
        self.assertEqual(stmt.currency, "SEK")
        self.assertEqual(stmt.bank_bic, "HANDSESS")
        self.assertEqual(stmt.from_date, date(2024, 1, 1))
        self.assertEqual(stmt.to_date, date(2024, 1, 15))

    def test_parse_v8(self):
        stmts = camt053.parse(_CAMT053_V8_XML)
        self.assertEqual(len(stmts), 1)
        self.assertEqual(stmts[0].iban, "SE4550000000058398257466")

    def test_balances(self):
        stmt = camt053.parse(_CAMT053_V2_XML)[0]
        self.assertEqual(stmt.opening_balance, Decimal("100000.00"))
        self.assertEqual(stmt.closing_balance, Decimal("115000.00"))

    def test_transaction_fields(self):
        stmt = camt053.parse(_CAMT053_V2_XML)[0]
        self.assertEqual(len(stmt.transactions), 1)
        tx = stmt.transactions[0]
        self.assertEqual(tx.amount, Decimal("15000.00"))
        self.assertEqual(tx.credit_debit, "CRDT")
        self.assertEqual(tx.booking_date, date(2024, 1, 10))
        self.assertEqual(tx.acct_svcr_ref, "SVC-REF-001")
        self.assertEqual(tx.party_name, "Customer AB")
        self.assertEqual(tx.party_iban, "SE7280000810340009783242")
        self.assertEqual(tx.structured_ref, "1234566")
        self.assertEqual(tx.domain_code, "PMNT")
        self.assertEqual(tx.family_code, "RCDT")
        self.assertEqual(tx.proprietary_code, "K04")

    def test_bad_namespace_raises(self):
        bad = _CAMT053_V2_XML.replace(
            b"urn:iso:std:iso:20022:tech:xsd:camt.053.001.02",
            b"urn:example:bad",
        )
        with self.assertRaises(ValueError):
            camt053.parse(bad)

    def test_malformed_xml_raises(self):
        with self.assertRaises(ValueError):
            camt053.parse(b"not xml at all")


class TestOCR(unittest.TestCase):
    # Payload "123456" → Luhn check digit = 6 → valid OCR = "1234566"
    def test_valid_ocr(self):
        self.assertTrue(validate_ocr("1234566"))

    def test_invalid_ocr(self):
        self.assertFalse(validate_ocr("1234560"))

    def test_normalize_valid(self):
        self.assertEqual(normalize_ocr("1234566"), "1234566")

    def test_normalize_invalid(self):
        self.assertIsNone(normalize_ocr("9999990"))

    def test_too_short(self):
        self.assertFalse(validate_ocr("1"))

    def test_non_digit(self):
        self.assertFalse(validate_ocr("123ABC"))


class TestSwedishIBAN(unittest.TestCase):
    # SE45 5000 0000 0583 9825 7466 — Swedbank/SEB range, valid check digits
    _VALID = "SE4550000000058398257466"

    def test_validate_valid(self):
        self.assertTrue(validate_se_iban(self._VALID))

    def test_validate_wrong_country(self):
        self.assertFalse(validate_se_iban("DE89370400440532013000"))

    def test_validate_wrong_length(self):
        self.assertFalse(validate_se_iban("SE45500000000583982574"))

    def test_roundtrip(self):
        clearing, account = iban_to_clearing_account(self._VALID)
        rebuilt = clearing_account_to_iban(clearing, account)
        self.assertEqual(rebuilt, self._VALID)

    def test_clearing_to_bank(self):
        # 6000-6999 → Handelsbanken
        self.assertEqual(clearing_to_bank_name(6200), "Handelsbanken")
        # 5000-5999 → SEB
        self.assertEqual(clearing_to_bank_name(5500), "SEB")
        # 1200-1399 → Danske Bank
        self.assertEqual(clearing_to_bank_name(1300), "Danske Bank")


class TestBankgiro(unittest.TestCase):
    # Bankgiro 795-6253: full-number Luhn(7956253) → sum=30 → valid
    def test_valid_bg(self):
        self.assertIsNotNone(normalize_bankgiro("7956253"))

    def test_format_bg(self):
        result = format_bankgiro("7956253")
        self.assertEqual(result, "795-6253")

    def test_invalid_bg(self):
        self.assertIsNone(normalize_bankgiro("7956258"))

    def test_valid_pg(self):
        # Plusgiro 123456-6 → full-number Luhn(1234566) → valid
        self.assertIsNotNone(normalize_plusgiro("1234566"))


class TestBankProfiles(unittest.TestCase):
    def test_lookup_by_bic(self):
        self.assertEqual(get_profile(bic="HANDSESS").name, "Handelsbanken")
        self.assertEqual(get_profile(bic="NDEASESS").name, "Nordea")
        self.assertEqual(get_profile(bic="ESSESESS").name, "SEB")
        self.assertEqual(get_profile(bic="SWEDSESS").name, "Swedbank")

    def test_lookup_by_name(self):
        self.assertEqual(get_profile(bank_name="Handelsbanken AB").name, "Handelsbanken")
        self.assertEqual(get_profile(bank_name="Nordea Bank").name, "Nordea")

    def test_unknown_falls_back(self):
        self.assertEqual(get_profile(bic="XXXXXXXX").name, "Generic")

    def test_handelsbanken_tx_code(self):
        label = HANDELSBANKEN.resolve_tx_type("K04", "PMNT", "RCDT", "VCOM")
        self.assertEqual(label, "Incoming Domestic Payment")

    def test_iso_fallback(self):
        label = get_profile().resolve_tx_type("", "PMNT", "RCDT", "VCOM")
        self.assertEqual(label, "Incoming Credit Transfer")


if __name__ == "__main__":
    unittest.main()
