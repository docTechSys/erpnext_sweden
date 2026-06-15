"""
Swedish IBAN utilities.

Swedish IBANs: SE + 2 check digits + 20 digits
The 20 digits encode: 4-digit clearing number + 0-padded account number.

IBAN check digit algorithm (ISO 13616):
  Move the 4 leading chars to the end, replace letters with digits (A=10…Z=35),
  compute mod 97 — result must be 1.

Clearing number ranges by bank (non-exhaustive, covers the major banks):
  Handelsbanken: 6000–6999
  Nordea:        1100–1199, 1400–2099, 3000–3399, 3410–3781
  SEB:           5000–5999
  Swedbank:      7000–8999 (also 7000–7999 via savings banks)
  Danske Bank:   1200–1399
  Länsförsäkringar: 3400–3409, 9060–9069
  ICA Banken:    9270–9279
  Skandiabanken: 9150–9169
  Ålandsbanken:  2310–2318 (also 6610–6619 in Sweden)
"""

_CLEARING_TO_BANK: list[tuple[range, str]] = [
    (range(1100, 1200), "Nordea"),
    (range(1200, 1400), "Danske Bank"),
    (range(1400, 2100), "Nordea"),
    (range(2310, 2319), "Ålandsbanken"),
    (range(3000, 3400), "Nordea"),
    (range(3400, 3410), "Länsförsäkringar Bank"),
    (range(3410, 3782), "Nordea"),
    (range(3782, 3790), "Nordea"),
    (range(3790, 3792), "Nordea"),
    (range(5000, 6000), "SEB"),
    (range(6000, 7000), "Handelsbanken"),
    (range(6610, 6620), "Ålandsbanken"),
    (range(7000, 9000), "Swedbank"),
    (range(9020, 9030), "Länsförsäkringar Bank"),
    (range(9040, 9050), "Citibank"),
    (range(9060, 9070), "Länsförsäkringar Bank"),
    (range(9090, 9095), "Royal Bank of Scotland"),
    (range(9100, 9110), "Riksgälden"),
    (range(9120, 9125), "Danske Bank"),
    (range(9130, 9135), "Danske Bank"),
    (range(9150, 9170), "Skandiabanken"),
    (range(9180, 9190), "Danske Bank"),
    (range(9230, 9240), "Marginalen Bank"),
    (range(9270, 9280), "ICA Banken"),
    (range(9280, 9290), "Resurs Bank"),
    (range(9300, 9350), "Sparbanken Syd"),
    (range(9400, 9450), "Forex Bank"),
    (range(9460, 9470), "GE Money Bank"),
    (range(9470, 9480), "Fortis Bank"),
    (range(9500, 9550), "Nordnet Bank"),
    (range(9550, 9570), "Avanza Bank"),
    (range(9960, 9970), "Nordea"),
]


def clearing_to_bank_name(clearing: int) -> str:
    """Return the bank name for a Swedish clearing number, or 'Unknown'."""
    for r, name in _CLEARING_TO_BANK:
        if clearing in r:
            return name
    return "Unknown"


def _mod97(number_str: str) -> int:
    remainder = 0
    for ch in number_str:
        remainder = (remainder * 10 + int(ch)) % 97
    return remainder


def validate_se_iban(iban: str) -> bool:
    """Return True if the string is a valid Swedish IBAN."""
    iban = iban.replace(" ", "").upper()
    if not iban.startswith("SE") or len(iban) != 24:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    return _mod97(numeric) == 1


def iban_to_clearing_account(iban: str) -> tuple[str, str] | None:
    """
    Convert a Swedish IBAN to (clearing_number, account_number).
    Returns None for invalid IBANs.
    The 20-digit BBAN encodes: 4-digit clearing + 16-digit zero-padded account.
    """
    iban = iban.replace(" ", "").upper()
    if not validate_se_iban(iban):
        return None
    bban = iban[4:]  # 20 digits
    clearing = bban[:4]
    account = bban[4:].lstrip("0") or "0"
    return clearing, account


def clearing_account_to_iban(clearing: str, account: str) -> str:
    """
    Build a Swedish IBAN from clearing number + account number.
    Pads account to 16 digits after the 4-digit clearing number.
    """
    bban = clearing.zfill(4) + account.zfill(16)
    rearranged = bban + "SE00"
    numeric = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    check = str(98 - _mod97(numeric)).zfill(2)
    return f"SE{check}{bban}"
