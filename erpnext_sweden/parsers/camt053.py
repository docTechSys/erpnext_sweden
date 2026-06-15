"""
camt.053 (BankToCustomerStatement) XML parser.

Supports both camt.053.001.02 (v2, current Swedish bank standard) and
camt.053.001.08 (v8, mandatory for SEPA from 2025, SWIFT from 2027-28).

The parser is namespace-aware but lenient: it probes for the namespace from
the document root so minor namespace variations from different banks work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# Namespace constants
# ---------------------------------------------------------------------------

_NS_V2 = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"
_NS_V8 = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
_SUPPORTED_NS = {_NS_V2, _NS_V8}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ParsedBalance:
    type_code: str  # OPBD, CLBD, CLAV, ITBD, …
    amount: Decimal
    currency: str
    credit_debit: str  # CRDT or DBIT
    date: date | None = None


@dataclass
class ParsedTransaction:
    """Normalised representation of one camt.053 <Ntry> (entry)."""

    # Core booking info
    amount: Decimal
    currency: str
    credit_debit: str  # CRDT | DBIT
    status: str  # BOOK | PDNG | INFO

    booking_date: date | None = None
    value_date: date | None = None

    # Bank-assigned reference — key for duplicate detection
    acct_svcr_ref: str = ""

    # Transaction classification
    domain_code: str = ""        # e.g. PMNT
    family_code: str = ""        # e.g. RCDT
    subfamily_code: str = ""     # e.g. VCOM
    proprietary_code: str = ""   # bank-specific code

    # Free-text description (may be assembled from multiple sources)
    description: str = ""

    # Remittance info
    unstructured_ref: str = ""   # RmtInf/Ustrd
    structured_ref: str = ""     # RmtInf/Strd/CdtrRefInf/Ref (OCR)
    end_to_end_id: str = ""

    # Counterparty
    party_name: str = ""
    party_iban: str = ""
    party_account_number: str = ""  # non-IBAN (BG, PG, clearing+account)
    party_bic: str = ""

    # Human-readable label (set by bank profile or BgMax parser)
    transaction_type: str = ""


@dataclass
class ParsedStatement:
    """Normalised representation of one camt.053 <Stmt>."""

    statement_id: str = ""
    message_id: str = ""
    creation_datetime: datetime | None = None

    from_date: date | None = None
    to_date: date | None = None

    # Account identification (one of these will be set)
    iban: str = ""
    other_account_id: str = ""   # BG or PG number
    other_account_issuer: str = ""  # BG | PG
    currency: str = "SEK"
    account_name: str = ""

    # Bank/servicer identification
    bank_bic: str = ""
    bank_name: str = ""

    balances: list[ParsedBalance] = field(default_factory=list)
    transactions: list[ParsedTransaction] = field(default_factory=list)

    @property
    def opening_balance(self) -> Decimal | None:
        for b in self.balances:
            if b.type_code == "OPBD":
                return b.amount if b.credit_debit == "CRDT" else -b.amount
        return None

    @property
    def closing_balance(self) -> Decimal | None:
        for b in self.balances:
            if b.type_code == "CLBD":
                return b.amount if b.credit_debit == "CRDT" else -b.amount
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_namespace(root: ET.Element) -> str:
    """Extract the ISO 20022 namespace from the root element."""
    m = re.match(r"\{(.+)\}", root.tag)
    ns = m.group(1) if m else ""
    if ns not in _SUPPORTED_NS:
        raise ValueError(
            f"Unsupported namespace '{ns}'. "
            f"Expected one of: {', '.join(sorted(_SUPPORTED_NS))}"
        )
    return ns


def _tag(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _find(el: ET.Element, ns: str, *path: str) -> ET.Element | None:
    current = el
    for name in path:
        current = current.find(_tag(ns, name))
        if current is None:
            return None
    return current


def _findall(el: ET.Element, ns: str, name: str) -> list[ET.Element]:
    return el.findall(_tag(ns, name))


def _parse_date(el: ET.Element | None) -> date | None:
    txt = _text(el)
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt[:10]).date()
    except ValueError:
        return None


def _parse_datetime(el: ET.Element | None) -> datetime | None:
    txt = _text(el)
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt[:19])
    except ValueError:
        return None


def _parse_amount(el: ET.Element | None) -> tuple[Decimal, str]:
    """Return (amount, currency) from an <Amt Ccy="SEK">1234.56</Amt> element."""
    if el is None:
        return Decimal("0"), ""
    ccy = el.attrib.get("Ccy", "")
    try:
        return Decimal(_text(el) or "0"), ccy
    except Exception:
        return Decimal("0"), ccy


# ---------------------------------------------------------------------------
# Balance parsing
# ---------------------------------------------------------------------------


def _parse_balance(bal: ET.Element, ns: str) -> ParsedBalance:
    type_el = _find(bal, ns, "Tp", "CdOrPrtry", "Cd")
    type_code = _text(type_el)

    amt_el = _find(bal, ns, "Amt")
    amount, currency = _parse_amount(amt_el)

    cdi = _text(_find(bal, ns, "CdtDbtInd"))

    date_el = _find(bal, ns, "Dt", "Dt")
    if date_el is None:
        date_el = _find(bal, ns, "Dt", "DtTm")
    bal_date = _parse_date(date_el)

    return ParsedBalance(
        type_code=type_code,
        amount=amount,
        currency=currency,
        credit_debit=cdi,
        date=bal_date,
    )


# ---------------------------------------------------------------------------
# Transaction (entry) parsing
# ---------------------------------------------------------------------------


def _parse_tx_details(tx: ET.Element, ns: str) -> dict:
    """Extract fields from a <TxDtls> element."""
    result: dict = {}

    # End-to-end ID
    result["end_to_end_id"] = _text(_find(tx, ns, "Refs", "EndToEndId"))

    # Remittance info
    rmtinf = _find(tx, ns, "RmtInf")
    if rmtinf is not None:
        result["unstructured_ref"] = _text(_find(rmtinf, ns, "Ustrd"))
        # Structured OCR reference
        strd = _find(rmtinf, ns, "Strd")
        if strd is not None:
            result["structured_ref"] = _text(
                _find(strd, ns, "CdtrRefInf", "Ref")
            )

    # Related parties — pick Debtor or Creditor depending on direction
    rltd = _find(tx, ns, "RltdPties")
    if rltd is not None:
        for party_tag, acct_tag in (("Dbtr", "DbtrAcct"), ("Cdtr", "CdtrAcct")):
            party_nm = _text(_find(rltd, ns, party_tag, "Nm"))
            if party_nm:
                result["party_name"] = party_nm
            acct_id = _find(rltd, ns, acct_tag, "Id")
            if acct_id is not None:
                iban = _text(_find(acct_id, ns, "IBAN"))
                if iban:
                    result["party_iban"] = iban
                else:
                    result["party_account_number"] = _text(
                        _find(acct_id, ns, "Othr", "Id")
                    )

    # Related agents (counterparty BIC)
    rltd_agts = _find(tx, ns, "RltdAgts")
    if rltd_agts is not None:
        for agt_tag in ("DbtrAgt", "CdtrAgt"):
            bic = _text(_find(rltd_agts, ns, agt_tag, "FinInstnId", "BIC"))
            if bic:
                result["party_bic"] = bic
                break

    return result


def _parse_entry(ntry: ET.Element, ns: str) -> ParsedTransaction:
    amt_el = _find(ntry, ns, "Amt")
    amount, currency = _parse_amount(amt_el)
    credit_debit = _text(_find(ntry, ns, "CdtDbtInd"))
    status = _text(_find(ntry, ns, "Sts"))

    # Booking and value dates
    booking_date = _parse_date(_find(ntry, ns, "BookgDt", "Dt")) or _parse_date(
        _find(ntry, ns, "BookgDt", "DtTm")
    )
    value_date = _parse_date(_find(ntry, ns, "ValDt", "Dt")) or _parse_date(
        _find(ntry, ns, "ValDt", "DtTm")
    )

    acct_svcr_ref = _text(_find(ntry, ns, "AcctSvcrRef"))

    # Bank transaction code
    bktxcd = _find(ntry, ns, "BkTxCd")
    domain_code = family_code = subfamily_code = proprietary_code = ""
    if bktxcd is not None:
        domain_code = _text(_find(bktxcd, ns, "Domn", "Cd"))
        family_code = _text(_find(bktxcd, ns, "Domn", "Fmly", "Cd"))
        subfamily_code = _text(_find(bktxcd, ns, "Domn", "Fmly", "SubFmlyCd"))
        proprietary_code = _text(_find(bktxcd, ns, "Prtry", "Cd"))

    # Additional info / narration
    description = _text(_find(ntry, ns, "AddtlNtryInf"))

    # Merge details from (potentially multiple) TxDtls sub-elements
    tx_fields: dict = {}
    ntry_dtls = _find(ntry, ns, "NtryDtls")
    if ntry_dtls is not None:
        for tx_dtls in _findall(ntry_dtls, ns, "TxDtls"):
            tx_fields.update({k: v for k, v in _parse_tx_details(tx_dtls, ns).items() if v})

    # Compose description from available text fields
    if not description:
        description = tx_fields.get("unstructured_ref", "") or tx_fields.get("structured_ref", "")

    return ParsedTransaction(
        amount=amount,
        currency=currency,
        credit_debit=credit_debit,
        status=status,
        booking_date=booking_date,
        value_date=value_date,
        acct_svcr_ref=acct_svcr_ref,
        domain_code=domain_code,
        family_code=family_code,
        subfamily_code=subfamily_code,
        proprietary_code=proprietary_code,
        description=description,
        unstructured_ref=tx_fields.get("unstructured_ref", ""),
        structured_ref=tx_fields.get("structured_ref", ""),
        end_to_end_id=tx_fields.get("end_to_end_id", ""),
        party_name=tx_fields.get("party_name", ""),
        party_iban=tx_fields.get("party_iban", ""),
        party_account_number=tx_fields.get("party_account_number", ""),
        party_bic=tx_fields.get("party_bic", ""),
    )


# ---------------------------------------------------------------------------
# Statement parsing
# ---------------------------------------------------------------------------


def _parse_statement(stmt: ET.Element, ns: str, message_id: str, creation_dt: datetime | None) -> ParsedStatement:
    ps = ParsedStatement(
        statement_id=_text(_find(stmt, ns, "Id")),
        message_id=message_id,
        creation_datetime=creation_dt,
    )

    # Period
    frtoddt = _find(stmt, ns, "FrToDt")
    if frtoddt is not None:
        ps.from_date = _parse_date(_find(frtoddt, ns, "FrDtTm")) or _parse_date(
            _find(frtoddt, ns, "FrDt")
        )
        ps.to_date = _parse_date(_find(frtoddt, ns, "ToDtTm")) or _parse_date(
            _find(frtoddt, ns, "ToDt")
        )

    # Account identification
    acct = _find(stmt, ns, "Acct")
    if acct is not None:
        acct_id = _find(acct, ns, "Id")
        if acct_id is not None:
            iban_el = _find(acct_id, ns, "IBAN")
            if iban_el is not None:
                ps.iban = _text(iban_el)
            else:
                othr = _find(acct_id, ns, "Othr")
                if othr is not None:
                    ps.other_account_id = _text(_find(othr, ns, "Id"))
                    ps.other_account_issuer = _text(_find(othr, ns, "Issr"))

        ps.currency = _text(_find(acct, ns, "Ccy")) or "SEK"
        ps.account_name = _text(_find(acct, ns, "Nm"))

        # Servicer (bank identity)
        svcr = _find(acct, ns, "Svcr")
        if svcr is not None:
            ps.bank_bic = _text(_find(svcr, ns, "FinInstnId", "BIC"))
            ps.bank_name = _text(_find(svcr, ns, "FinInstnId", "Nm"))

    # Balances
    for bal in _findall(stmt, ns, "Bal"):
        ps.balances.append(_parse_balance(bal, ns))

    # Transactions
    for ntry in _findall(stmt, ns, "Ntry"):
        ps.transactions.append(_parse_entry(ntry, ns))

    return ps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(xml_bytes: bytes) -> list[ParsedStatement]:
    """
    Parse a camt.053 XML file and return a list of ParsedStatement objects.
    One file may contain multiple statements (one per account).

    Raises ValueError for unrecognised namespaces or malformed XML.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    ns = _detect_namespace(root)
    bktocstmrstmt = root.find(_tag(ns, "BkToCstmrStmt"))
    if bktocstmrstmt is None:
        raise ValueError("Root element does not contain <BkToCstmrStmt>")

    grphdr = _find(bktocstmrstmt, ns, "GrpHdr")
    message_id = _text(_find(grphdr, ns, "MsgId")) if grphdr is not None else ""
    creation_dt = _parse_datetime(_find(grphdr, ns, "CreDtTm")) if grphdr is not None else None

    statements = []
    for stmt in _findall(bktocstmrstmt, ns, "Stmt"):
        statements.append(_parse_statement(stmt, ns, message_id, creation_dt))

    return statements
