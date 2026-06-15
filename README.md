# ERPNext Sweden

Swedish banking extensions for ERPNext — ISO 20022 statement import (camt.053 / BgMax) and payment export (pain.001).

## Why this app?

Sweden's payment infrastructure is migrating to ISO 20022 throughout 2026. Legacy Bankgirot formats (BgMax, LB, KI Lön) are being shut down, and all businesses must receive bank statements via **camt.053 by 8 September 2026** and stop sending BgMax files by **27 November 2026**. This app bridges ERPNext with the new standard and covers the transition period.

## Supported banks

| Bank | camt.053 | BgMax | pain.001 |
|------|----------|-------|----------|
| Handelsbanken | ✓ (v2 + extended) | — | ✓ |
| Nordea | ✓ (v2 + extended) | — | ✓ |
| SEB | ✓ v2 | — | ✓ |
| Swedbank | ✓ v2 | — | ✓ |
| Danske Bank | ✓ v2 | — | ✓ |
| Länsförsäkringar | ✓ (generic) | — | ✓ |
| Ålandsbanken | ✓ (generic) | — | ✓ |
| **Bankgirot** | — | ✓ | — |

All banks that produce camt.053.001.08 (v8, SEPA mandatory from Nov 2025, SWIFT from 2027–28) are also supported — the parser detects the version automatically.

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/doctech/erpnext_sweden
bench install-app erpnext_sweden
bench --site <site-name> migrate
bench build
```

Requires ERPNext v16+.

---

## Feature 1 — Bank Statement Import (camt.053 and BgMax)

### What it does

Imports electronic bank statements from any of the supported banks directly into ERPNext Bank Transactions, ready for reconciliation.

- Auto-detects file format (XML → camt.053, text → BgMax)
- Auto-detects the bank from BIC or bank name in the file
- Maps bank-specific proprietary transaction codes to human-readable types
- Validates and extracts Swedish OCR references for auto-reconciliation
- Handles all Swedish account identifiers: IBAN, Bankgiro, Plusgiro, clearing+account

### Usage

1. Go to **ERPNext Sweden → Sweden Bank Statement Import → New**
2. Select the **Bank Account** you are importing for
3. Attach the **camt.053 XML** or **BgMax** file from your bank
4. Click **Parse File** — the app reads the file and shows a preview of all transactions with amounts, dates, party names, and references
5. Review the preview, then click **Import Transactions** — each row becomes a submitted **Bank Transaction** in ERPNext
6. Go to **Accounts → Bank Reconciliation** to match imported transactions against invoices and payments

### BgMax transition note

BgMax (Bankgiro Inbetalningar) support is included for the transition period. Bankgirot shuts down BgMax on **27 November 2026** — after that date only camt.053/054 will carry incoming Bankgiro payment details. The import form accepts both formats transparently until then.

### OCR reference reconciliation

Swedish Bankgiro/Plusgiro incoming payments carry an OCR reference (structured mod-10 check digit reference). The importer validates the OCR checksum and stores it in the `reference_number` field of the Bank Transaction, enabling ERPNext's automatic payment matching to link the transaction to the correct Sales Invoice.

---

## Feature 2 — Payment Export (pain.001)

### What it does

Generates ISO 20022 **pain.001.001.03** (CustomerCreditTransferInitiation) XML files from ERPNext Payment Orders, replacing the legacy Bankgirot LB and KI Lön formats.

Supports all Swedish payment types in one file:
- Domestic supplier payments (IBAN or Bankgiro)
- Plusgiro payments
- Salary payments
- International / SEPA transfers

### Usage

1. Create a **Payment Order** in ERPNext (Accounts → Payment Order → New) and add the Payment Entry references you want to pay
2. Set the **Company Bank Account** on the Payment Order — the app reads its IBAN and BIC
3. Submit the Payment Order
4. Click the **Sweden** button group → **Generate pain.001 (Sweden)**
5. The XML file is generated and downloaded automatically, and attached to the Payment Order for your records
6. Upload the file to your bank's corporate portal or SFTP endpoint

### Supplier bank account setup

For each supplier, go to **Accounting → Bank Account** and add their bank account:
- **IBAN field**: Swedish IBAN (SE + 22 digits) — used for domestic or SEPA transfers
- **Bank Account No field**: Bankgiro number (e.g. `795-6253`) or Plusgiro number (e.g. `12345-6`) — the app validates the Luhn check digit and uses the correct scheme name (`BGNR` or `PGNR`)

### pain.001 format versions

The app generates **pain.001.001.03**, which all major Swedish banks accept. Migration to pain.001.001.09 is planned when Swedish banks require it (expected 2026–2028 based on individual bank timelines).

---

## Swedish-specific field handling

### OCR references
Swedish OCR references follow the **Bankgirot mod-10 (Luhn)** standard: a 2–25 digit string where the last digit is a check digit. The app validates every reference it encounters and flags invalid ones. OCR references are stored in `structured_ref` (camt.053) and used as payment references in pain.001 (`RmtInf/Strd/CdtrRefInf`).

### IBAN ↔ clearing+account
Swedish IBANs encode a 4-digit clearing number followed by a zero-padded account number. The app can convert in both directions and derives the bank name from the clearing number for display.

### Bankgiro and Plusgiro
Validated with Luhn mod-10 against the full number (including check digit). Formatted as `NNN-NNNN` (Bankgiro) or `N-N` (Plusgiro). Encoded in pain.001 with proprietary scheme names `BGNR` and `PGNR` as specified in the Bankgirot ISO 20022 profile.

### Beneficiary name (mandatory from April 2026)
As of **14 April 2026** (account transfers/salaries) and **8 September 2026** (Bankgiro/Plusgiro), Swedish clearing requires the beneficiary name in payment files. The `Cdtr/Nm` element is always populated in generated pain.001 files.

### Structured addresses (mandatory from November 2026)
From **15 November 2026**, unstructured postal addresses are rejected in SEPA, Swedish domestic, and SWIFT payments. Address handling for future versions of this app.

---

## Key Swedish deadlines

| Date | What changes |
|------|-------------|
| 14 Apr 2026 | Beneficiary name mandatory; LB supplier payment format phased out |
| 8 Sep 2026 | camt.053/054 mandatory in new Swedish clearing; BG/PG payments move to ISO 20022 |
| 27 Nov 2026 | BgMax (Bankgiro Inbetalningar) completely discontinued |
| 15 Nov 2026 | Unstructured addresses rejected in SEPA, Swedish domestic, SWIFT |
| 2027–2028 | SWIFT migrates to camt.053 v8; Swedish banks follow |

---

## Architecture

```
erpnext_sweden/
├── parsers/
│   ├── camt053.py          # camt.053 v2/v8 XML parser → ParsedStatement
│   ├── bgmax.py            # BgMax fixed-width parser → ParsedStatement
│   └── bank_profiles.py    # Bank-specific transaction code mappings
├── payments/
│   ├── pain001.py          # pain.001.001.03 XML generator (pure Python)
│   └── api.py              # Frappe integration (reads Payment Order → XML)
├── utils/
│   ├── ocr.py              # Swedish OCR reference validation (Luhn)
│   ├── swedish_iban.py     # SE IBAN ↔ clearing+account, bank name lookup
│   └── bankgiro.py         # Bankgiro/Plusgiro validation and formatting
├── erpnext_sweden/
│   └── doctype/
│       ├── sweden_bank_statement_import/   # Import UI doctype
│       └── sweden_bank_statement_transaction/  # Child table
└── public/js/
    └── payment_order.js    # "Generate pain.001" button on Payment Order
```

The parsers and generator are pure Python with no Frappe dependency — they are fully unit-testable without a running ERPNext instance.

---

## Running tests

```bash
cd apps/erpnext_sweden
python3 -m unittest discover -s erpnext_sweden/tests -v
```

106 tests covering:
- camt.053 v2 and v8 parsing
- BgMax record parsing, multi-section files, ISO-8859-1 encoding, öre conversion
- OCR reference validation
- Swedish IBAN validation and roundtrip conversion
- Bankgiro/Plusgiro validation
- Bank profile lookup by BIC and bank name
- pain.001 XML structure, all creditor account types, multi-batch files, edge cases

---

## Contributing

This app uses `pre-commit` for code formatting and linting:

```bash
cd apps/erpnext_sweden
pre-commit install
```

Configured tools: **ruff**, **eslint**, **prettier**, **pyupgrade**.

---

## License

MIT
