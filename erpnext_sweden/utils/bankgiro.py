"""
Swedish Bankgiro and Plusgiro number utilities.

Bankgiro (BG): 7–8 digits with a mod-10 (Luhn) check digit.
  Displayed as NNN-NNNN or NNNN-NNNN.

Plusgiro (PG): 2–8 digits, also mod-10 Luhn check digit.
  Displayed as N-N, NN-N, etc.

Both use the same Luhn algorithm as Swedish OCR references.
"""


def _luhn_check(digits: str) -> bool:
    # Validate a full number (including check digit).
    # Double every second digit from the right, skipping the rightmost (check digit).
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def normalize_bankgiro(bg: str) -> str | None:
    """
    Normalize a Bankgiro number to plain digits and validate it.
    Returns the normalized string (7–8 digits) or None if invalid.
    """
    digits = "".join(ch for ch in bg if ch.isdigit())
    if len(digits) not in (7, 8):
        return None
    return digits if _luhn_check(digits) else None


def format_bankgiro(bg: str) -> str | None:
    """Return a BG number formatted as NNN-NNNN or NNNN-NNNN."""
    digits = normalize_bankgiro(bg)
    if digits is None:
        return None
    return f"{digits[:-4]}-{digits[-4:]}"


def normalize_plusgiro(pg: str) -> str | None:
    """
    Normalize a Plusgiro number to plain digits and validate it.
    Returns the normalized string (2–8 digits) or None if invalid.
    """
    digits = "".join(ch for ch in pg if ch.isdigit())
    if not (2 <= len(digits) <= 8):
        return None
    return digits if _luhn_check(digits) else None


def format_plusgiro(pg: str) -> str | None:
    """Return a PG number formatted with a dash before the last digit."""
    digits = normalize_plusgiro(pg)
    if digits is None:
        return None
    return f"{digits[:-1]}-{digits[-1]}"
