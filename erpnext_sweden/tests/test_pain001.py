"""
Unit tests for the pain.001.001.03 XML generator.

Tests cover:
  - XML structure and namespace
  - Group header fields (MsgId, CreDtTm, NbOfTxs, CtrlSum)
  - Payment information block fields
  - All three Swedish creditor account types: IBAN, Bankgiro, Plusgiro
  - OCR structured reference vs unstructured free-text
  - Multiple batches in one file
  - Category purpose (SUPP, SALA)
  - Error handling for empty input
"""

import unittest
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from erpnext_sweden.payments.pain001 import (
    CreditTransfer,
    DebtorAccount,
    InitiatingParty,
    PaymentBatch,
    generate,
)


_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


def _tag(local: str) -> str:
    return f"{{{_NS}}}{local}"


def _find(root: ET.Element, *path: str) -> ET.Element | None:
    current = root
    for name in path:
        current = current.find(_tag(name))
        if current is None:
            return None
    return current


def _text(root: ET.Element, *path: str) -> str:
    el = _find(root, *path)
    return (el.text or "").strip() if el is not None else ""


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_INITIATING_PARTY = InitiatingParty(
    name="Test Company AB",
    org_number="5560000000",
    bic="HANDSESS",
)

_DEBTOR = DebtorAccount(
    iban="SE4550000000058398257466",
    bic="HANDSESS",
    currency="SEK",
    name="Test Company AB",
)

_FIXED_DT = datetime(2024, 1, 15, 8, 0, 0)
_EXEC_DATE = date(2024, 1, 17)

_TRANSFER_IBAN = CreditTransfer(
    end_to_end_id="INV-2024-001",
    amount=Decimal("1500.00"),
    currency="SEK",
    creditor_name="Supplier AB",
    execution_date=_EXEC_DATE,
    creditor_iban="SE7280000810340009783242",
    creditor_bic="ESSESESS",
    ocr_reference="1234566",
    category_purpose="SUPP",
)

_TRANSFER_BG = CreditTransfer(
    end_to_end_id="INV-2024-002",
    amount=Decimal("2500.50"),
    currency="SEK",
    creditor_name="Service Partner AB",
    execution_date=_EXEC_DATE,
    creditor_bg="7956253",
    unstructured_ref="Invoice 2024-002",
    category_purpose="SUPP",
)

_TRANSFER_PG = CreditTransfer(
    end_to_end_id="SALARY-2024-01",
    amount=Decimal("45000.00"),
    currency="SEK",
    creditor_name="Employee Name",
    execution_date=_EXEC_DATE,
    creditor_pg="1234566",
    category_purpose="SALA",
)


def _make_batch(*transfers, batch_id="BATCH-001") -> PaymentBatch:
    return PaymentBatch(
        payment_info_id=batch_id,
        execution_date=_EXEC_DATE,
        debtor=_DEBTOR,
        transfers=list(transfers),
    )


def _parse(xml_bytes: bytes) -> ET.Element:
    return ET.fromstring(xml_bytes)


# ---------------------------------------------------------------------------
# Tests: XML structure
# ---------------------------------------------------------------------------

class TestPain001Structure(unittest.TestCase):
    def setUp(self):
        batch = _make_batch(_TRANSFER_IBAN)
        self.xml = generate(_INITIATING_PARTY, [batch], "MSG-001", _FIXED_DT)
        self.root = _parse(self.xml)

    def test_xml_declaration(self):
        self.assertTrue(self.xml.startswith(b"<?xml"))

    def test_utf8_encoding_declared(self):
        self.assertIn(b"encoding='utf-8'", self.xml.lower())

    def test_root_tag_is_document(self):
        self.assertEqual(self.root.tag, _tag("Document"))

    def test_root_child_is_custmrcdttrfintn(self):
        child = self.root.find(_tag("CstmrCdtTrfInitn"))
        self.assertIsNotNone(child)

    def test_namespace(self):
        self.assertIn(_NS, self.xml.decode())


class TestPain001GroupHeader(unittest.TestCase):
    def setUp(self):
        batch = _make_batch(_TRANSFER_IBAN, _TRANSFER_BG)
        self.xml = generate(_INITIATING_PARTY, [batch], "MSG-GHDR-001", _FIXED_DT)
        root = _parse(self.xml)
        self.initn = root.find(_tag("CstmrCdtTrfInitn"))

    def test_message_id(self):
        self.assertEqual(_text(self.initn, "GrpHdr", "MsgId"), "MSG-GHDR-001")

    def test_creation_datetime(self):
        self.assertEqual(_text(self.initn, "GrpHdr", "CreDtTm"), "2024-01-15T08:00:00")

    def test_number_of_transactions(self):
        self.assertEqual(_text(self.initn, "GrpHdr", "NbOfTxs"), "2")

    def test_control_sum(self):
        # 1500.00 + 2500.50 = 4000.50
        self.assertEqual(_text(self.initn, "GrpHdr", "CtrlSum"), "4000.50")

    def test_initiating_party_name(self):
        self.assertEqual(_text(self.initn, "GrpHdr", "InitgPty", "Nm"), "Test Company AB")

    def test_org_number(self):
        org_id = _text(self.initn, "GrpHdr", "InitgPty", "Id", "OrgId", "Othr", "Id")
        self.assertEqual(org_id, "5560000000")


class TestPain001PaymentInfo(unittest.TestCase):
    def setUp(self):
        batch = _make_batch(_TRANSFER_IBAN, batch_id="PMTINF-TEST")
        xml = generate(_INITIATING_PARTY, [batch], "MSG-001", _FIXED_DT)
        initn = _parse(xml).find(_tag("CstmrCdtTrfInitn"))
        self.pmtinf = initn.find(_tag("PmtInf"))

    def test_payment_info_id(self):
        self.assertEqual(_text(self.pmtinf, "PmtInfId"), "PMTINF-TEST")

    def test_payment_method(self):
        self.assertEqual(_text(self.pmtinf, "PmtMtd"), "TRF")

    def test_requested_execution_date(self):
        self.assertEqual(_text(self.pmtinf, "ReqdExctnDt"), "2024-01-17")

    def test_debtor_name(self):
        self.assertEqual(_text(self.pmtinf, "Dbtr", "Nm"), "Test Company AB")

    def test_debtor_iban(self):
        iban = _text(self.pmtinf, "DbtrAcct", "Id", "IBAN")
        self.assertEqual(iban, "SE4550000000058398257466")

    def test_debtor_currency(self):
        self.assertEqual(_text(self.pmtinf, "DbtrAcct", "Ccy"), "SEK")

    def test_debtor_bic(self):
        bic = _text(self.pmtinf, "DbtrAgt", "FinInstnId", "BIC")
        self.assertEqual(bic, "HANDSESS")


# ---------------------------------------------------------------------------
# Tests: creditor account types
# ---------------------------------------------------------------------------

class TestCreditorIBAN(unittest.TestCase):
    def setUp(self):
        batch = _make_batch(_TRANSFER_IBAN)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-001", _FIXED_DT)
        initn = _parse(xml).find(_tag("CstmrCdtTrfInitn"))
        pmtinf = initn.find(_tag("PmtInf"))
        self.cdttx = pmtinf.find(_tag("CdtTrfTxInf"))

    def test_creditor_name(self):
        self.assertEqual(_text(self.cdttx, "Cdtr", "Nm"), "Supplier AB")

    def test_creditor_iban(self):
        iban = _text(self.cdttx, "CdtrAcct", "Id", "IBAN")
        self.assertEqual(iban, "SE7280000810340009783242")

    def test_creditor_bic(self):
        bic = _text(self.cdttx, "CdtrAgt", "FinInstnId", "BIC")
        self.assertEqual(bic, "ESSESESS")

    def test_end_to_end_id(self):
        self.assertEqual(_text(self.cdttx, "PmtId", "EndToEndId"), "INV-2024-001")

    def test_amount(self):
        amt = self.cdttx.find(_tag("Amt")).find(_tag("InstdAmt"))
        self.assertEqual(amt.text, "1500.00")
        self.assertEqual(amt.attrib["Ccy"], "SEK")

    def test_ocr_structured_ref(self):
        ref = _text(self.cdttx, "RmtInf", "Strd", "CdtrRefInf", "Ref")
        self.assertEqual(ref, "1234566")

    def test_ocr_type_code(self):
        code = _text(self.cdttx, "RmtInf", "Strd", "CdtrRefInf", "Tp", "CdOrPrtry", "Cd")
        self.assertEqual(code, "SCOR")

    def test_category_purpose(self):
        code = _text(self.cdttx, "PmtTpInf", "CtgyPurp", "Cd")
        self.assertEqual(code, "SUPP")


class TestCreditorBankgiro(unittest.TestCase):
    def setUp(self):
        batch = _make_batch(_TRANSFER_BG)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-001", _FIXED_DT)
        initn = _parse(xml).find(_tag("CstmrCdtTrfInitn"))
        pmtinf = initn.find(_tag("PmtInf"))
        self.cdttx = pmtinf.find(_tag("CdtTrfTxInf"))

    def test_bg_account_id(self):
        acct_id = _text(self.cdttx, "CdtrAcct", "Id", "Othr", "Id")
        self.assertEqual(acct_id, "7956253")

    def test_bg_scheme_name(self):
        prtry = _text(self.cdttx, "CdtrAcct", "Id", "Othr", "SchmeNm", "Prtry")
        self.assertEqual(prtry, "BGNR")

    def test_no_iban_element(self):
        iban = _find(self.cdttx, "CdtrAcct", "Id", "IBAN")
        self.assertIsNone(iban)

    def test_unstructured_ref(self):
        ref = _text(self.cdttx, "RmtInf", "Ustrd")
        self.assertEqual(ref, "Invoice 2024-002")

    def test_amount(self):
        amt = self.cdttx.find(_tag("Amt")).find(_tag("InstdAmt"))
        self.assertEqual(amt.text, "2500.50")


class TestCreditorPlusgiro(unittest.TestCase):
    def setUp(self):
        batch = _make_batch(_TRANSFER_PG)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-001", _FIXED_DT)
        initn = _parse(xml).find(_tag("CstmrCdtTrfInitn"))
        pmtinf = initn.find(_tag("PmtInf"))
        self.cdttx = pmtinf.find(_tag("CdtTrfTxInf"))

    def test_pg_account_id(self):
        acct_id = _text(self.cdttx, "CdtrAcct", "Id", "Othr", "Id")
        self.assertEqual(acct_id, "1234566")

    def test_pg_scheme_name(self):
        prtry = _text(self.cdttx, "CdtrAcct", "Id", "Othr", "SchmeNm", "Prtry")
        self.assertEqual(prtry, "PGNR")

    def test_salary_category_purpose(self):
        code = _text(self.cdttx, "PmtTpInf", "CtgyPurp", "Cd")
        self.assertEqual(code, "SALA")


# ---------------------------------------------------------------------------
# Tests: multi-batch file
# ---------------------------------------------------------------------------

class TestMultiBatch(unittest.TestCase):
    def setUp(self):
        batch1 = _make_batch(_TRANSFER_IBAN, batch_id="BATCH-1")
        batch2 = _make_batch(_TRANSFER_BG, _TRANSFER_PG, batch_id="BATCH-2")
        xml = generate(_INITIATING_PARTY, [batch1, batch2], "MSG-MULTI", _FIXED_DT)
        self.initn = _parse(xml).find(_tag("CstmrCdtTrfInitn"))

    def test_total_tx_count(self):
        # 1 + 2 = 3
        self.assertEqual(_text(self.initn, "GrpHdr", "NbOfTxs"), "3")

    def test_control_sum(self):
        # 1500.00 + 2500.50 + 45000.00 = 49000.50
        self.assertEqual(_text(self.initn, "GrpHdr", "CtrlSum"), "49000.50")

    def test_two_pmtinf_blocks(self):
        pmtinfs = self.initn.findall(_tag("PmtInf"))
        self.assertEqual(len(pmtinfs), 2)

    def test_batch2_has_two_transfers(self):
        pmtinfs = self.initn.findall(_tag("PmtInf"))
        second = pmtinfs[1]
        txs = second.findall(_tag("CdtTrfTxInf"))
        self.assertEqual(len(txs), 2)


# ---------------------------------------------------------------------------
# Tests: field truncation and edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_long_creditor_name_truncated(self):
        long_name = "A" * 200
        transfer = CreditTransfer(
            end_to_end_id="EDGE-001",
            amount=Decimal("100.00"),
            currency="SEK",
            creditor_name=long_name,
            execution_date=_EXEC_DATE,
            creditor_iban="SE4550000000058398257466",
        )
        batch = _make_batch(transfer)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-EDGE", _FIXED_DT)
        root = _parse(xml)
        initn = root.find(_tag("CstmrCdtTrfInitn"))
        cdttx = initn.find(_tag("PmtInf")).find(_tag("CdtTrfTxInf"))
        name = _text(cdttx, "Cdtr", "Nm")
        self.assertLessEqual(len(name), 140)

    def test_long_end_to_end_id_truncated(self):
        transfer = CreditTransfer(
            end_to_end_id="X" * 100,
            amount=Decimal("1.00"),
            currency="SEK",
            creditor_name="Test",
            execution_date=_EXEC_DATE,
            creditor_iban="SE4550000000058398257466",
        )
        batch = _make_batch(transfer)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-EDGE2", _FIXED_DT)
        root = _parse(xml)
        initn = root.find(_tag("CstmrCdtTrfInitn"))
        cdttx = initn.find(_tag("PmtInf")).find(_tag("CdtTrfTxInf"))
        e2e = _text(cdttx, "PmtId", "EndToEndId")
        self.assertLessEqual(len(e2e), 35)

    def test_no_remittance_when_empty(self):
        transfer = CreditTransfer(
            end_to_end_id="NOREF-001",
            amount=Decimal("50.00"),
            currency="SEK",
            creditor_name="Test",
            execution_date=_EXEC_DATE,
            creditor_iban="SE4550000000058398257466",
        )
        batch = _make_batch(transfer)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-EDGE3", _FIXED_DT)
        root = _parse(xml)
        initn = root.find(_tag("CstmrCdtTrfInitn"))
        cdttx = initn.find(_tag("PmtInf")).find(_tag("CdtTrfTxInf"))
        rmtinf = _find(cdttx, "RmtInf")
        self.assertIsNone(rmtinf)

    def test_auto_message_id_generated(self):
        batch = _make_batch(_TRANSFER_IBAN)
        xml = generate(_INITIATING_PARTY, [batch])
        initn = _parse(xml).find(_tag("CstmrCdtTrfInitn"))
        msg_id = _text(initn, "GrpHdr", "MsgId")
        self.assertGreater(len(msg_id), 0)

    def test_iban_spaces_stripped(self):
        transfer = CreditTransfer(
            end_to_end_id="IBAN-SPACE",
            amount=Decimal("100.00"),
            currency="SEK",
            creditor_name="Test",
            execution_date=_EXEC_DATE,
            creditor_iban="SE45 5000 0000 0583 9825 7466",
        )
        batch = _make_batch(transfer)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-SP", _FIXED_DT)
        root = _parse(xml)
        initn = root.find(_tag("CstmrCdtTrfInitn"))
        cdttx = initn.find(_tag("PmtInf")).find(_tag("CdtTrfTxInf"))
        iban = _text(cdttx, "CdtrAcct", "Id", "IBAN")
        self.assertNotIn(" ", iban)


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrors(unittest.TestCase):
    def test_empty_batches_raises(self):
        with self.assertRaises(ValueError):
            generate(_INITIATING_PARTY, [])

    def test_empty_transfers_raises(self):
        empty_batch = PaymentBatch(
            payment_info_id="EMPTY",
            execution_date=_EXEC_DATE,
            debtor=_DEBTOR,
            transfers=[],
        )
        with self.assertRaises(ValueError):
            generate(_INITIATING_PARTY, [empty_batch])

    def test_valid_xml_parseable(self):
        batch = _make_batch(_TRANSFER_IBAN, _TRANSFER_BG, _TRANSFER_PG)
        xml = generate(_INITIATING_PARTY, [batch], "MSG-VALID", _FIXED_DT)
        # Should not raise
        ET.fromstring(xml)


if __name__ == "__main__":
    unittest.main()
