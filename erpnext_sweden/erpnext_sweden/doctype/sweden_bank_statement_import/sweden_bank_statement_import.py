import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_sweden.parsers import bgmax, camt053
from erpnext_sweden.parsers.bank_profiles import get_profile
from erpnext_sweden.utils.ocr import normalize_ocr


class SwedenBankStatementImport(Document):
    def validate(self):
        if self.status == "Draft" and self.statement_file:
            self.transactions = []
            self.import_errors = ""

    @frappe.whitelist()
    def parse_file(self):
        """Parse the attached camt.053 XML or BgMax file and populate the transactions table."""
        if not self.statement_file:
            frappe.throw(_("Please attach a camt.053 XML or BgMax file first."))

        file_bytes = _read_file(self.statement_file)

        try:
            if bgmax.is_bgmax(file_bytes):
                statements = bgmax.parse(file_bytes)
                format_label = "BgMax"
            else:
                statements = camt053.parse(file_bytes)
                format_label = "camt.053"
        except ValueError as exc:
            self.status = "Error"
            self.import_errors = str(exc)
            self.save()
            frappe.throw(str(exc))

        if not statements:
            frappe.throw(_("No statements found in the file."))

        stmt = statements[0]
        profile = get_profile(bic=stmt.bank_bic, bank_name=stmt.bank_name)

        self.detected_bank = profile.name if profile.name != "Generic" else stmt.bank_name or ""
        self.message_id = stmt.message_id
        self.from_date = stmt.from_date
        self.to_date = stmt.to_date
        self.currency = stmt.currency or "SEK"

        ob = stmt.opening_balance
        cb = stmt.closing_balance
        self.opening_balance = float(ob) if ob is not None else None
        self.closing_balance = float(cb) if cb is not None else None

        self.transactions = []
        for tx in stmt.transactions:
            tx_type = profile.resolve_tx_type(
                tx.proprietary_code, tx.domain_code, tx.family_code, tx.subfamily_code
            )
            ref = tx.structured_ref or tx.unstructured_ref or tx.end_to_end_id
            ocr = normalize_ocr(tx.structured_ref) if tx.structured_ref else None
            party_account = tx.party_iban or tx.party_account_number

            self.append("transactions", {
                "date": tx.booking_date or tx.value_date,
                "amount": float(tx.amount),
                "credit_debit": tx.credit_debit,
                "description": tx.description or tx.unstructured_ref,
                "reference_number": ref,
                "transaction_id": tx.acct_svcr_ref,
                "party_name": tx.party_name,
                "party_iban": party_account,
                "transaction_type": tx_type,
                "domain_code": f"{tx.domain_code}/{tx.family_code}/{tx.subfamily_code}".strip("/"),
                "ocr_reference": ocr or "",
            })

        self.transaction_count = len(self.transactions)
        self.imported_count = 0
        self.status = "Parsed"
        self.import_errors = ""
        self.save()
        frappe.msgprint(_("Parsed {0} transactions ({1}) from {2}.").format(
            self.transaction_count, format_label, self.detected_bank or "bank"
        ))

    @frappe.whitelist()
    def import_transactions(self):
        """Create ERPNext Bank Transaction records for all parsed rows."""
        if self.status not in ("Parsed", "Partially Imported"):
            frappe.throw(_("Please parse the file before importing."))

        bank_account = self.bank_account
        errors = []
        imported = 0

        for row in self.transactions:
            if row.bank_transaction:
                continue  # already imported

            if not row.date or not row.amount:
                continue

            try:
                bt = _create_bank_transaction(row, bank_account)
                row.bank_transaction = bt.name
                imported += 1
            except Exception as exc:
                errors.append(f"Row {row.idx}: {exc}")

        self.imported_count = imported
        self.status = "Imported" if not errors else "Partially Imported"
        self.import_errors = "\n".join(errors) if errors else ""
        self.save()

        if errors:
            frappe.msgprint(
                _("Imported {0} transactions with {1} error(s). See Import Errors section.").format(
                    imported, len(errors)
                ),
                indicator="orange",
            )
        else:
            frappe.msgprint(
                _("Successfully imported {0} transactions.").format(imported),
                indicator="green",
            )


def _read_file(file_url: str) -> bytes:
    """Read an attached file and return its content as bytes."""
    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_path = file_doc.get_full_path()
    with open(file_path, "rb") as f:
        return f.read()


def _create_bank_transaction(row, bank_account: str):
    """Create and submit a Bank Transaction from a parsed row."""
    deposit = withdrawal = 0.0
    if row.credit_debit == "CRDT":
        deposit = row.amount
    else:
        withdrawal = row.amount

    description_parts = [p for p in [row.description, row.party_name] if p]
    description = " | ".join(description_parts) or row.reference_number or ""

    bt = frappe.get_doc({
        "doctype": "Bank Transaction",
        "date": row.date,
        "bank_account": bank_account,
        "deposit": deposit,
        "withdrawal": withdrawal,
        "description": description[:140],  # ERPNext field limit
        "reference_number": (row.ocr_reference or row.reference_number or "")[:140],
        "transaction_id": row.transaction_id or "",
        "transaction_type": row.transaction_type or "",
        "bank_party_name": (row.party_name or "")[:140],
        "bank_party_iban": row.party_iban or "",
    })
    bt.insert(ignore_permissions=True)
    bt.submit()
    return bt
