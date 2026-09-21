from decimal import Decimal

from django import template

from core.thai import thai_date, thai_datetime

register = template.Library()


@register.filter(name="thaidate")
def thaidate_filter(value, style="short"):
    return thai_date(value, style)


@register.filter(name="thaidatetime")
def thaidatetime_filter(value):
    return thai_datetime(value)


@register.filter
def baht(value):
    if value in (None, ""):
        return ""
    return f"{Decimal(value):,.2f}"
