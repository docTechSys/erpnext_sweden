"""
Frappe-facing API for pain.001 payment export.

Reads data from ERPNext Payment Order / Payment Order Reference and
feeds it to the pure-Python pain.001 generator.
"""

from __future__ import annotations

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import now_datetime

from erpnext_sweden.payments.pain001 import (
    CreditTransfer,
    DebtorAccount,
    InitiatingParty,
    PaymentBatch,
    generate,
)
from erpnext_sweden.utils.bankgiro import normalize_bankgiro, normalize_plusgiro
from erpnext_sweden.utils.swedish_iban import validate_se_iban


@frappe.whitelist()
def generate_pain001(payment_order: str) -> dict:
    """
    Generate a pain.001 XML file from a submitted ERPNext Payment Order.

    Returns a dict with:
      - file_url: URL of the saved XML file (for browser download)
      - filename: suggested filename
      - transfer_count: number of transfers included
    """
    doc = frappe.get_doc("Payment Order", payment_order)
    if doc.docstatus != 1:
        frappe.throw(_("Payment Order must be submitted before generating pain.001."))

    company = frappe.get_doc("Company", doc.company)
    debtor_acct = _get_debtor_account(doc)
    initiating_party = _get_initiating_party(company, debtor_acct)

    transfers = []
    for row in doc.references:
        transfer = _build_transfer(row, doc.posting_date)
        if transfer:
            transfers.append(transfer)

    if not transfers:
        frappe.throw(_("No valid transfers found. Ensure all suppliers have a bank account with IBAN, Bankgiro, or Plusgiro."))

    batch = PaymentBatch(
        payment_info_id=doc.name[:35],
        execution_date=doc.posting_date,
        debtor=debtor_acct,
        transfers=transfers,
    )

    xml_bytes = generate(
        initiating_party=initiating_party,
        batches=[batch],
        message_id=doc.name[:35],
        creation_dt=now_datetime(),
    )

    filename = f"pain001_{doc.name}_{doc.posting_date}.xml"
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": xml_bytes,
        "is_private": 1,
        "attached_to_doctype": "Payment Order",
        "attached_to_name": doc.name,
    })
    file_doc.save(ignore_permissions=True)

    return {
        "file_url": file_doc.file_url,
        "filename": filename,
        "transfer_count": len(transfers),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_debtor_account(doc) -> DebtorAccount:
    """Extract DebtorAccount from the Payment Order's company bank account."""
    if not doc.company_bank_account:
        frappe.throw(_("Payment Order must have a Company Bank Account set."))

    ba = frappe.get_doc("Bank Account", doc.company_bank_account)
    iban = (ba.iban or "").replace(" ", "").upper()
    if not iban:
        frappe.throw(_("Company Bank Account '{0}' has no IBAN set.").format(ba.name))

    bank = frappe.get_doc("Bank", ba.bank) if ba.bank else None
    bic = (bank.swift_number if bank else "") or ""

    return DebtorAccount(
        iban=iban,
        bic=bic,
        currency="SEK",
        name=ba.account_name or doc.company,
    )


def _get_initiating_party(company, debtor: DebtorAccount) -> InitiatingParty:
    tax_id = getattr(company, "tax_id", "") or ""
    # Swedish org numbers: strip hyphens and spaces
    org_number = "".join(ch for ch in tax_id if ch.isdigit())
    return InitiatingParty(
        name=company.company_name,
        org_number=org_number,
        bic=debtor.bic,
    )


def _build_transfer(row, execution_date) -> CreditTransfer | None:
    """Build a CreditTransfer from one Payment Order Reference row."""
    if not row.bank_account:
        frappe.log_error(f"Payment Order Reference '{row.name}' has no bank account — skipped")
        return None

    ba = frappe.get_doc("Bank Account", row.bank_account)
    iban, bg, pg = _resolve_account(ba)
    if not (iban or bg or pg):
        frappe.log_error(
            f"Bank account '{ba.name}' for supplier '{row.supplier}' has no recognisable "
            f"IBAN, Bankgiro, or Plusgiro — skipped"
        )
        return None

    bank = frappe.get_doc("Bank", ba.bank) if ba.bank else None
    creditor_bic = (bank.swift_number if bank else "") or ""

    # Fetch the linked Payment Entry to get the reference / OCR
    ocr = ""
    unstructured = row.payment_reference or ""
    if row.reference_doctype == "Payment Entry" and row.reference_name:
        pe = frappe.get_doc("Payment Entry", row.reference_name)
        ocr = pe.reference_no or ""
        if not unstructured:
            unstructured = pe.reference_no or ""

    return CreditTransfer(
        end_to_end_id=(row.payment_reference or row.reference_name or row.name)[:35],
        amount=row.amount,
        currency="SEK",
        creditor_name=(ba.account_name or row.supplier or "")[:140],
        execution_date=execution_date,
        creditor_iban=iban,
        creditor_bg=bg,
        creditor_pg=pg,
        creditor_bic=creditor_bic,
        ocr_reference=ocr,
        unstructured_ref=unstructured,
        category_purpose="SUPP",
    )


def _resolve_account(ba) -> tuple[str, str, str]:
    """
    Return (iban, bankgiro, plusgiro) from a Bank Account document.
    Exactly one will be non-empty in the happy path; all empty means unknown.
    """
    iban_raw = (ba.iban or "").replace(" ", "").upper()
    if iban_raw and validate_se_iban(iban_raw):
        return iban_raw, "", ""

    account_no = (ba.bank_account_no or "").strip()
    if account_no:
        bg = normalize_bankgiro(account_no)
        if bg:
            return "", bg, ""
        pg = normalize_plusgiro(account_no)
        if pg:
            return "", "", pg
        # Treat as raw account number (clearing + account)
        return "", "", ""

    return "", "", ""
