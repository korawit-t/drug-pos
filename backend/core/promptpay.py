"""
PromptPay QR payload (Thai QR Payment, EMVCo merchant-presented mode).

Generated locally — no bank connection. The customer's banking app reads the
amount from the QR; the cashier still has to check that the money arrived.
"""

from decimal import Decimal

PROMPTPAY_AID = "A000000677010111"


def _field(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF), as required by EMVCo QR."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def _target(promptpay_id: str) -> tuple[str, str]:
    digits = "".join(ch for ch in promptpay_id if ch.isdigit())
    if len(digits) >= 15:
        return "03", digits  # e-wallet
    if len(digits) >= 13:
        return "02", digits  # national ID / tax ID
    # mobile: 0812345678 -> 0066812345678
    return "01", ("66" + digits[1:] if digits.startswith("0") else digits).rjust(13, "0")


def generate_payload(promptpay_id: str, amount: Decimal | None = None) -> str:
    target_tag, target = _target(promptpay_id)
    parts = [
        _field("00", "01"),
        _field("01", "12" if amount else "11"),
        _field("29", _field("00", PROMPTPAY_AID) + _field(target_tag, target)),
        _field("58", "TH"),
        _field("53", "764"),
    ]
    if amount:
        parts.append(_field("54", f"{Decimal(amount):.2f}"))
    payload = "".join(parts) + "6304"
    return payload + f"{crc16_ccitt(payload.encode('ascii')):04X}"
