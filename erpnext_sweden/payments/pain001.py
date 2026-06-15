"""
pain.001.001.03 (CustomerCreditTransferInitiation) XML generator.

Produces ISO 20022 payment initiation files for Swedish outgoing payments.
Supports all account types used in Sweden:
  - IBAN (domestic and SEPA)
  - Bankgiro (BG number, scheme name "BGNR")
  - Plusgiro (PG number, scheme name "PGNR")

This module is pure Python with no Frappe dependency — it receives plain
dataclass instances and returns an XML bytes object.  The Frappe integration
layer (payments/api.py) is responsible for fetching data from ERPNext.

Reference standards:
  pain.001.001.03 — ISO 20022, CGI-MP and Bankgirot Swedish profile
  Handelsbanken, Nordea, SEB, Swedbank all accept this version.
  Migration to pain.001.001.09 is planned from 2026-2028.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET


_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


# ---------------------------------------------------------------------------
# Data classes (Frappe-independent)
# ---------------------------------------------------------------------------


@dataclass
class InitiatingParty:
    """The company initiating the payments."""
    name: str
    org_number: str = ""   # Swedish org number, e.g. "5560000000"
    bic: str = ""


@dataclass
class DebtorAccount:
    """The company's bank account being debited."""
    iban: str
    bic: str
    currency: str = "SEK"
    name: str = ""


@dataclass
class CreditTransfer:
    """One outgoing payment."""
    end_to_end_id: str          # Unique reference per transfer (invoice number etc.)
    amount: Decimal
    currency: str
    creditor_name: str
    execution_date: date

    # Creditor account — exactly one of these must be set
    creditor_iban: str = ""
    creditor_bg: str = ""        # Bankgiro number (digits only, e.g. "7956253")
    creditor_pg: str = ""        # Plusgiro number (digits only)
    creditor_account_no: str = ""  # Clearing + account for domestic without IBAN

    creditor_bic: str = ""

    # Remittance / reference
    ocr_reference: str = ""      # Structured OCR reference (preferred)
    unstructured_ref: str = ""   # Free text reference (fallback)

    # Category purpose
    category_purpose: str = ""   # SUPP (supplier), SALA (salary), TAXP, …


@dataclass
class PaymentBatch:
    """
    Groups transfers that share the same debtor account and execution date.
    One PaymentBatch → one <PmtInf> block in the pain.001 file.
    """
    payment_info_id: str
    execution_date: date
    debtor: DebtorAccount
    transfers: list[CreditTransfer] = field(default_factory=list)

    @property
    def total_amount(self) -> Decimal:
        return sum(t.amount for t in self.transfers)

    @property
    def count(self) -> int:
        return len(self.transfers)


# ---------------------------------------------------------------------------
# XML builder helpers
# ---------------------------------------------------------------------------


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{_NS}}}{tag}")
    if text is not None:
        el.text = text
    return el


def _amount_str(amount: Decimal) -> str:
    return f"{amount:.2f}"


# ---------------------------------------------------------------------------
# Element builders
# ---------------------------------------------------------------------------


def _build_group_header(
    root: ET.Element,
    message_id: str,
    creation_dt: datetime,
    initiating_party: InitiatingParty,
    total_transfers: int,
    control_sum: Decimal,
) -> None:
    grphdr = _sub(root, "GrpHdr")
    _sub(grphdr, "MsgId", message_id)
    _sub(grphdr, "CreDtTm", creation_dt.strftime("%Y-%m-%dT%H:%M:%S"))
    _sub(grphdr, "NbOfTxs", str(total_transfers))
    _sub(grphdr, "CtrlSum", _amount_str(control_sum))
    initg_pty = _sub(grphdr, "InitgPty")
    _sub(initg_pty, "Nm", initiating_party.name[:140])
    if initiating_party.org_number:
        id_el = _sub(initg_pty, "Id")
        org_id = _sub(id_el, "OrgId")
        othr = _sub(org_id, "Othr")
        _sub(othr, "Id", initiating_party.org_number)


def _build_debtor_agent(pmtinf: ET.Element, bic: str) -> None:
    dbtr_agt = _sub(pmtinf, "DbtrAgt")
    fin = _sub(dbtr_agt, "FinInstnId")
    if bic:
        _sub(fin, "BIC", bic)
    else:
        _sub(fin, "Othr").append(ET.Element(f"{{{_NS}}}Id"))
        fin.find(f"{{{_NS}}}Othr/{{{_NS}}}Id").text = "NOTPROVIDED"  # type: ignore[union-attr]


def _build_creditor_agent(cdttx: ET.Element, bic: str) -> None:
    if not bic:
        return
    cdtr_agt = _sub(cdttx, "CdtrAgt")
    _sub(_sub(cdtr_agt, "FinInstnId"), "BIC", bic)


def _build_creditor_account(cdttx: ET.Element, transfer: CreditTransfer) -> None:
    cdtr_acct = _sub(cdttx, "CdtrAcct")
    id_el = _sub(cdtr_acct, "Id")

    if transfer.creditor_iban:
        _sub(id_el, "IBAN", transfer.creditor_iban.replace(" ", "").upper())
    elif transfer.creditor_bg:
        othr = _sub(id_el, "Othr")
        _sub(othr, "Id", transfer.creditor_bg)
        schme = _sub(othr, "SchmeNm")
        _sub(schme, "Prtry", "BGNR")
    elif transfer.creditor_pg:
        othr = _sub(id_el, "Othr")
        _sub(othr, "Id", transfer.creditor_pg)
        schme = _sub(othr, "SchmeNm")
        _sub(schme, "Prtry", "PGNR")
    elif transfer.creditor_account_no:
        othr = _sub(id_el, "Othr")
        _sub(othr, "Id", transfer.creditor_account_no)


def _build_remittance(cdttx: ET.Element, transfer: CreditTransfer) -> None:
    if not transfer.ocr_reference and not transfer.unstructured_ref:
        return
    rmtinf = _sub(cdttx, "RmtInf")
    if transfer.ocr_reference:
        strd = _sub(rmtinf, "Strd")
        cdtr_ref = _sub(strd, "CdtrRefInf")
        tp = _sub(cdtr_ref, "Tp")
        cd_or = _sub(tp, "CdOrPrtry")
        _sub(cd_or, "Cd", "SCOR")
        _sub(cdtr_ref, "Ref", transfer.ocr_reference)
    elif transfer.unstructured_ref:
        _sub(rmtinf, "Ustrd", transfer.unstructured_ref[:140])


def _build_credit_transfer(pmtinf: ET.Element, transfer: CreditTransfer) -> None:
    cdttx = _sub(pmtinf, "CdtTrfTxInf")

    # Payment ID
    pmtid = _sub(cdttx, "PmtId")
    _sub(pmtid, "EndToEndId", transfer.end_to_end_id[:35])

    # Amount
    amt = _sub(cdttx, "Amt")
    inst_amt = _sub(amt, "InstdAmt", _amount_str(transfer.amount))
    inst_amt.set("Ccy", transfer.currency)

    # Category purpose
    if transfer.category_purpose:
        pmt_tp = _sub(cdttx, "PmtTpInf")
        ctgy = _sub(pmt_tp, "CtgyPurp")
        _sub(ctgy, "Cd", transfer.category_purpose)

    # Creditor agent (BIC)
    _build_creditor_agent(cdttx, transfer.creditor_bic)

    # Creditor name
    cdtr = _sub(cdttx, "Cdtr")
    _sub(cdtr, "Nm", transfer.creditor_name[:140])

    # Creditor account
    _build_creditor_account(cdttx, transfer)

    # Remittance info
    _build_remittance(cdttx, transfer)


def _build_payment_info(doc_root: ET.Element, batch: PaymentBatch) -> None:
    pmtinf = _sub(doc_root, "PmtInf")
    _sub(pmtinf, "PmtInfId", batch.payment_info_id[:35])
    _sub(pmtinf, "PmtMtd", "TRF")
    _sub(pmtinf, "NbOfTxs", str(batch.count))
    _sub(pmtinf, "CtrlSum", _amount_str(batch.total_amount))

    # Payment type info
    pmt_tp = _sub(pmtinf, "PmtTpInf")
    svc = _sub(pmt_tp, "SvcLvl")
    # Use SEPA service level for EUR; for SEK use NURG (not-urgent domestic)
    _sub(svc, "Cd", "SEPA" if batch.debtor.currency == "EUR" else "NURG")

    _sub(pmtinf, "ReqdExctnDt", batch.execution_date.strftime("%Y-%m-%d"))

    # Debtor
    dbtr = _sub(pmtinf, "Dbtr")
    _sub(dbtr, "Nm", batch.debtor.name[:140])

    # Debtor account
    dbtr_acct = _sub(pmtinf, "DbtrAcct")
    id_el = _sub(dbtr_acct, "Id")
    _sub(id_el, "IBAN", batch.debtor.iban.replace(" ", "").upper())
    _sub(dbtr_acct, "Ccy", batch.debtor.currency)

    # Debtor agent
    _build_debtor_agent(pmtinf, batch.debtor.bic)

    for transfer in batch.transfers:
        _build_credit_transfer(pmtinf, transfer)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    initiating_party: InitiatingParty,
    batches: list[PaymentBatch],
    message_id: str | None = None,
    creation_dt: datetime | None = None,
) -> bytes:
    """
    Generate a pain.001.001.03 XML file.

    Returns UTF-8 encoded XML bytes with an XML declaration.

    Args:
        initiating_party: The company sending the payments.
        batches: One or more PaymentBatch objects (one per debtor account
                 and/or execution date grouping).
        message_id: Unique file identifier.  Auto-generated UUID if not given.
        creation_dt: File creation timestamp.  Defaults to now (UTC).

    Raises:
        ValueError: If batches is empty or any batch has no transfers.
    """
    if not batches:
        raise ValueError("At least one PaymentBatch is required")
    for b in batches:
        if not b.transfers:
            raise ValueError(f"PaymentBatch '{b.payment_info_id}' has no transfers")

    if message_id is None:
        message_id = str(uuid.uuid4())[:35]
    if creation_dt is None:
        creation_dt = datetime.utcnow()

    total_transfers = sum(b.count for b in batches)
    total_amount = sum(b.total_amount for b in batches)

    ET.register_namespace("", _NS)
    doc = ET.Element(f"{{{_NS}}}Document")
    root = ET.SubElement(doc, f"{{{_NS}}}CstmrCdtTrfInitn")

    _build_group_header(root, message_id, creation_dt, initiating_party, total_transfers, total_amount)

    for batch in batches:
        _build_payment_info(root, batch)

    tree = ET.ElementTree(doc)
    ET.indent(tree, space="  ")

    import io
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()
