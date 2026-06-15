"""
Swedish OCR reference validation.

OCR (Optical Character Recognition) references are structured payment
references used with Swedish Bankgiro and Plusgiro collections.
The standard is defined by Bankgirot and uses a mod-10 (Luhn) check digit.

References are 2–25 digits long. The last digit is a Luhn check digit.
Some banks append a length digit before the check digit (variant with length check).
"""


def _luhn_checksum(digits: str) -> int:
    """Return the Luhn mod-10 checksum digit for a string of digits."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (10 - (total % 10)) % 10


def validate_ocr(ref: str) -> bool:
    """Return True if ref is a valid Swedish OCR reference (mod-10 check digit)."""
    digits = ref.strip()
    if not digits.isdigit() or not (2 <= len(digits) <= 25):
        return False
    payload, check = digits[:-1], int(digits[-1])
    return _luhn_checksum(payload) == check


def normalize_ocr(ref: str) -> str | None:
    """Strip whitespace and non-digit characters; return None if not a valid OCR ref."""
    cleaned = "".join(ch for ch in ref if ch.isdigit())
    return cleaned if validate_ocr(cleaned) else None
