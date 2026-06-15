"""
Bank-specific profiles for Swedish camt.053 files.

Each profile maps proprietary BkTxCd codes to human-readable ERPNext
transaction types and resolves the bank name from BIC or statement metadata.

Sources:
  Handelsbanken: BTC appendix from Global Gateway documentation
  Nordea:        Corporate eGateway MIG camt.053.001.02
  SEB:           sebgroup.com integration documentation
  Swedbank:      ISO 20022 migration documentation 2026
  Danske Bank:   danskeci.com camt appendix
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BankProfile:
    name: str
    bics: frozenset[str]
    tx_code_map: dict[str, str]  # proprietary code -> human label

    def resolve_tx_type(self, proprietary_code: str, domain: str, family: str, subfamily: str) -> str:
        if proprietary_code and proprietary_code in self.tx_code_map:
            return self.tx_code_map[proprietary_code]
        return _iso_tx_label(domain, family, subfamily)


# ---------------------------------------------------------------------------
# ISO domain/family/subfamily → human label (fallback for all banks)
# ---------------------------------------------------------------------------

_ISO_LABELS: dict[tuple[str, str, str], str] = {
    ("PMNT", "RCDT", "VCOM"): "Incoming Credit Transfer",
    ("PMNT", "RCDT", "SALA"): "Salary Credit",
    ("PMNT", "RCDT", "OTHR"): "Other Incoming Credit",
    ("PMNT", "ICDT", "VCOM"): "Outgoing Credit Transfer",
    ("PMNT", "ICDT", "SALA"): "Salary Payment",
    ("PMNT", "ICDT", "OTHR"): "Other Outgoing Transfer",
    ("PMNT", "IRCT", "VCOM"): "Incoming Domestic Credit",
    ("PMNT", "DRFT", "FWDV"): "Forward Value Payment",
    ("PMNT", "CCRD", "POSP"): "Card Payment",
    ("PMNT", "CCRD", "CDPT"): "Card Deposit",
    ("CAMT", "MDOP", "FEES"): "Bank Fees",
    ("CAMT", "MDOP", "INTR"): "Interest",
    ("SECU", "SETT", "SETT"): "Securities Settlement",
}

_FAMILY_LABELS: dict[tuple[str, str], str] = {
    ("PMNT", "RCDT"): "Incoming Credit",
    ("PMNT", "ICDT"): "Outgoing Credit",
    ("PMNT", "RDDT"): "Incoming Direct Debit",
    ("PMNT", "IDDT"): "Outgoing Direct Debit",
    ("PMNT", "CCRD"): "Card Transaction",
    ("CAMT", "MDOP"): "Account Management",
}


def _iso_tx_label(domain: str, family: str, subfamily: str) -> str:
    label = _ISO_LABELS.get((domain, family, subfamily))
    if label:
        return label
    label = _FAMILY_LABELS.get((domain, family))
    if label:
        return label
    if domain:
        return f"{domain}/{family}/{subfamily}".strip("/")
    return "Transaction"


# ---------------------------------------------------------------------------
# Handelsbanken
# BICs: HANDSESS (Sweden), HANDSESSKH (clearing), HANDGB2L (UK), etc.
# Source: Global Gateway BTC appendix
# ---------------------------------------------------------------------------

_HANDELSBANKEN_TX_CODES: dict[str, str] = {
    "K04": "Incoming Domestic Payment",
    "K05": "Incoming International Transfer",
    "K06": "Bankgiro Incoming",
    "K07": "Plusgiro Incoming",
    "K10": "Outgoing Domestic Payment",
    "K11": "Outgoing International Transfer",
    "K16": "Bankgiro Outgoing",
    "K17": "Plusgiro Outgoing",
    "K20": "Salary Payment",
    "K21": "Tax Payment",
    "K30": "Card Purchase",
    "K31": "ATM Withdrawal",
    "K50": "Account Interest",
    "K51": "Bank Fee",
    "K60": "Direct Debit",
    "K61": "Autogiro Debit",
    "K62": "Autogiro Credit",
}

HANDELSBANKEN = BankProfile(
    name="Handelsbanken",
    bics=frozenset(["HANDSESS", "HANDSESSKH"]),
    tx_code_map=_HANDELSBANKEN_TX_CODES,
)

# ---------------------------------------------------------------------------
# Nordea
# BICs: NDEASESS (Sweden), NDEAFIHH (Finland), NDEADKKK (Denmark)
# Source: Nordea Corporate eGateway MIG camt.053.001.02
# ---------------------------------------------------------------------------

_NORDEA_TX_CODES: dict[str, str] = {
    "OWNT": "Own Account Transfer",
    "PAYR": "Supplier Payment",
    "SALA": "Salary Payment",
    "TAXP": "Tax Payment",
    "BKGR": "Bankgiro",
    "PLGR": "Plusgiro",
    "SEPA": "SEPA Credit Transfer",
    "WIRE": "International Wire Transfer",
    "FEES": "Bank Fee",
    "INTR": "Interest",
    "AGRD": "Autogiro Debit",
    "AGRC": "Autogiro Credit",
    "CARD": "Card Transaction",
    "ATMD": "ATM Withdrawal",
    "BGMX": "Bankgiro Incoming (BgMax)",
}

NORDEA = BankProfile(
    name="Nordea",
    bics=frozenset(["NDEASESS", "NDEAFIHH", "NDEADKKK", "NDEANOKK"]),
    tx_code_map=_NORDEA_TX_CODES,
)

# ---------------------------------------------------------------------------
# SEB (Skandinaviska Enskilda Banken)
# BIC: ESSESESS
# Source: sebgroup.com integration documentation
# ---------------------------------------------------------------------------

_SEB_TX_CODES: dict[str, str] = {
    "SE01": "Incoming Domestic Transfer",
    "SE02": "Outgoing Domestic Transfer",
    "SE03": "Incoming International Transfer",
    "SE04": "Outgoing International Transfer",
    "SE05": "Bankgiro Incoming",
    "SE06": "Bankgiro Outgoing",
    "SE07": "Plusgiro Incoming",
    "SE08": "Plusgiro Outgoing",
    "SE10": "Salary",
    "SE11": "Tax Payment",
    "SE20": "Card Purchase",
    "SE21": "ATM Cash",
    "SE30": "Bank Fee",
    "SE31": "Interest Debit",
    "SE32": "Interest Credit",
    "SE40": "Autogiro",
    "SE50": "Securities",
}

SEB = BankProfile(
    name="SEB",
    bics=frozenset(["ESSESESS"]),
    tx_code_map=_SEB_TX_CODES,
)

# ---------------------------------------------------------------------------
# Swedbank
# BICs: SWEDSESS, SWEDSESSXXX
# Source: Swedbank ISO 20022 migration documentation
# ---------------------------------------------------------------------------

_SWEDBANK_TX_CODES: dict[str, str] = {
    "CRED": "Incoming Credit",
    "DBIT": "Outgoing Debit",
    "BGKR": "Bankgiro Credit",
    "BGDT": "Bankgiro Debit",
    "PGKR": "Plusgiro Credit",
    "PGDT": "Plusgiro Debit",
    "LOWL": "Loan Withdrawal",
    "LREP": "Loan Repayment",
    "SACC": "Savings Account Transfer",
    "FEES": "Service Fee",
    "INTR": "Interest",
    "CARD": "Card Transaction",
    "ATMD": "ATM Withdrawal",
    "SALA": "Salary",
    "BENE": "Social Benefits",
    "AUTG": "Autogiro",
}

SWEDBANK = BankProfile(
    name="Swedbank",
    bics=frozenset(["SWEDSESS", "SWEDSESSXXX"]),
    tx_code_map=_SWEDBANK_TX_CODES,
)

# ---------------------------------------------------------------------------
# Danske Bank
# BIC: DABADKKK (Denmark), DABASESX (Sweden)
# Source: danskeci.com/ci/transaction-banking/instructions/iso-20022-xml
# ---------------------------------------------------------------------------

_DANSKE_TX_CODES: dict[str, str] = {
    "DB01": "Domestic Credit Transfer",
    "DB02": "International Transfer",
    "DB03": "SEPA Credit Transfer",
    "DB04": "Direct Debit",
    "DB05": "Card Payment",
    "DB10": "Fee",
    "DB11": "Interest",
    "DB20": "Salary",
    "DB30": "Bankgiro",
    "DB31": "Internal Transfer",
}

DANSKE_BANK = BankProfile(
    name="Danske Bank",
    bics=frozenset(["DABADKKK", "DABASESX", "DABABEBBXXX"]),
    tx_code_map=_DANSKE_TX_CODES,
)

# ---------------------------------------------------------------------------
# Länsförsäkringar Bank
# BIC: LFBASES1
# ---------------------------------------------------------------------------

LANSFORSAKRINGAR = BankProfile(
    name="Länsförsäkringar Bank",
    bics=frozenset(["LFBASES1"]),
    tx_code_map={},
)

# ---------------------------------------------------------------------------
# Ålandsbanken
# BICs: AABAFI22, AABASESS
# ---------------------------------------------------------------------------

ALANDSBANKEN = BankProfile(
    name="Ålandsbanken",
    bics=frozenset(["AABAFI22", "AABASESS"]),
    tx_code_map={},
)

# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

GENERIC = BankProfile(
    name="Generic",
    bics=frozenset(),
    tx_code_map={},
)

# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------

_ALL_PROFILES: list[BankProfile] = [
    HANDELSBANKEN,
    NORDEA,
    SEB,
    SWEDBANK,
    DANSKE_BANK,
    LANSFORSAKRINGAR,
    ALANDSBANKEN,
]

_BIC_INDEX: dict[str, BankProfile] = {
    bic: profile for profile in _ALL_PROFILES for bic in profile.bics
}

# Partial name → profile (for when BIC is absent but bank name is in the file)
_NAME_INDEX: dict[str, BankProfile] = {
    "handelsbanken": HANDELSBANKEN,
    "nordea": NORDEA,
    "seb": SEB,
    "skandinaviska enskilda": SEB,
    "swedbank": SWEDBANK,
    "danske": DANSKE_BANK,
    "länsförsäkringar": LANSFORSAKRINGAR,
    "alandsbanken": ALANDSBANKEN,
    "ålandsbanken": ALANDSBANKEN,
}


def get_profile(bic: str = "", bank_name: str = "") -> BankProfile:
    """Return the BankProfile for the given BIC or bank name, or GENERIC."""
    if bic:
        profile = _BIC_INDEX.get(bic.upper())
        if profile:
            return profile
    if bank_name:
        lower = bank_name.lower()
        for key, profile in _NAME_INDEX.items():
            if key in lower:
                return profile
    return GENERIC
