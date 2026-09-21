from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import ShopSettings
from inventory.models import Lot, Purchase, PurchaseItem
from sales.models import Sale, SaleItem


def _date_range(request):
    today = timezone.localdate()
    start = parse_date(request.GET.get("start") or "") or today.replace(day=1)
    end = parse_date(request.GET.get("end") or "") or today
    return start, end


def _context(request, **extra):
    start, end = _date_range(request)
    return {"shop": ShopSettings.load(), "start": start, "end": end, "today": timezone.localdate(), **extra}


@login_required
def index(request):
    return render(request, "reports/index.html", _context(request))


@login_required
def ky9(request):
    """บัญชีการซื้อยา — จากใบรับยาที่บันทึกเข้าสต็อกแล้ว (ไม่รวมยอดยกมา)"""
    start, end = _date_range(request)
    items = (
        PurchaseItem.objects.filter(
            purchase__status=Purchase.Status.POSTED,
            purchase__is_opening_balance=False,
            purchase__received_date__range=(start, end),
        )
        .select_related("purchase__supplier", "unit__product")
        .order_by("purchase__received_date", "purchase_id", "id")
    )
    return render(request, "reports/ky9.html", _context(request, items=items))


@login_required
def ky11(request):
    """บัญชีการขายยาอันตรายตามที่ อย. ประกาศ — เฉพาะบิลที่ไม่ถูกยกเลิก"""
    start, end = _date_range(request)
    items = (
        SaleItem.objects.filter(
            in_ky11_list=True,
            sale__status=Sale.Status.COMPLETED,
            sale__created_at__date__range=(start, end),
        )
        .select_related("sale__customer", "product", "confirmed_by")
        .prefetch_related("allocations__lot")
        .order_by("sale__created_at", "id")
    )
    return render(request, "reports/ky11.html", _context(request, items=items))


@login_required
def expiry(request):
    """ยาหมดอายุและใกล้หมดอายุที่ยังอยู่บนชั้น"""
    shop = ShopSettings.load()
    try:
        days = int(request.GET.get("days") or shop.near_expiry_days)
    except ValueError:
        days = shop.near_expiry_days
    today = timezone.localdate()
    lots = (
        Lot.objects.filter(qty_on_hand__gt=0, expiry_date__lte=today + timedelta(days=days))
        .select_related("product")
        .order_by("expiry_date", "product__trade_name")
    )
    return render(request, "reports/expiry.html", _context(request, lots=lots, days=days))
