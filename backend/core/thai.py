"""Dates are stored as ค.ศ.; everything a person reads (reports, receipts, labels) shows พ.ศ."""

import datetime

from django.utils import timezone

THAI_MONTHS_SHORT = [
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
]


def buddhist_year(year: int) -> int:
    return year + 543


def _as_local(value):
    if isinstance(value, datetime.datetime) and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def thai_date(value, style: str = "short") -> str:
    """
    short:  21/09/2569
    long:   21 ก.ย. 2569
    month:  09/2569   (expiry dates on labels)
    """
    if value is None:
        return ""
    value = _as_local(value)
    year = buddhist_year(value.year)
    if style == "long":
        return f"{value.day} {THAI_MONTHS_SHORT[value.month - 1]} {year}"
    if style == "month":
        return f"{value.month:02d}/{year}"
    return f"{value.day:02d}/{value.month:02d}/{year}"


def thai_datetime(value) -> str:
    if value is None:
        return ""
    value = _as_local(value)
    return f"{thai_date(value)} {value:%H:%M}"
