"""Dates are stored as ค.ศ.; everything a person reads (reports, receipts, labels) shows พ.ศ."""

import calendar
import datetime
import re

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


MONTH_ONLY = "เดือน/ปี"


def parse_expiry(value) -> datetime.date | None:
    """
    Expiry dates as printed on the box, the same forms the counter screen accepts:
    03/2028 (end of that month), 03/71 and 31/03/2571 (พ.ศ.), 2028-03-31, or a
    real date cell from Excel. Returns None when it can't be read.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if iso := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        year, month, day = (int(part) for part in iso.groups())
    else:
        parts = re.split(r"[/.\-\s]+", text)
        if not all(part.isdigit() for part in parts) or not 2 <= len(parts) <= 3:
            return None
        day = int(parts[0]) if len(parts) == 3 else None
        month, year = int(parts[-2]), _expand_year(parts[-1])
    if year is None:
        return None
    if year > 2400:
        year -= 543
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    last_day = calendar.monthrange(year, month)[1]
    if day is None:
        day = last_day  # a month means the end of that month
    if not 1 <= day <= last_day:
        return None
    return datetime.date(year, month, day)


def _expand_year(text: str) -> int | None:
    """Two digits: 60–99 is พ.ศ. (2560–2599), 00–59 is ค.ศ. (2000–2059)."""
    if len(text) == 2:
        value = int(text)
        return 2500 + value if value >= 60 else 2000 + value
    return int(text) if len(text) == 4 else None


def thai_datetime(value) -> str:
    if value is None:
        return ""
    value = _as_local(value)
    return f"{thai_date(value)} {value:%H:%M}"
