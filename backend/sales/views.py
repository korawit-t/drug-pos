from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from core.models import ShopSettings
from inventory.models import Product

from .models import Sale


def _sale(sale_id: int) -> Sale:
    return get_object_or_404(Sale.objects.select_related("cashier", "customer"), pk=sale_id)


@login_required
def receipt(request, sale_id: int):
    """ใบเสร็จกระดาษม้วน 80 มม."""
    sale = _sale(sale_id)
    items = list(sale.items.select_related("confirmed_by"))
    pharmacists = sorted({item.confirmed_by.label_name for item in items if item.confirmed_by})
    return render(
        request,
        "sales/receipt.html",
        {"shop": ShopSettings.load(), "sale": sale, "items": items, "pharmacists": pharmacists},
    )


@login_required
def labels(request, sale_id: int):
    """ฉลากยาขนาด 8 x 5 ซม. หนึ่งดวงต่อหนึ่งรายการยา (ไม่พิมพ์ให้สินค้าทั่วไป)"""
    sale = _sale(sale_id)
    items = [
        item
        for item in sale.items.select_related("product", "confirmed_by").prefetch_related("allocations__lot")
        if item.category != Product.Category.GENERAL
    ]
    for item in items:
        allocations = list(item.allocations.all())
        item.first_lot = allocations[0].lot if allocations else None
    return render(
        request,
        "sales/labels.html",
        {"shop": ShopSettings.load(), "sale": sale, "items": items, "buyer": sale.buyer_display},
    )
