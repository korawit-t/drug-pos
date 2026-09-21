from django.contrib import admin

from .models import Customer, Sale, SaleItem


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "price_level", "allergies")
    list_filter = ("price_level",)
    search_fields = ("name", "phone")


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    fields = ("description", "qty", "unit_name", "unit_price", "line_total", "dosage_text", "confirmed_by")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    """ดูได้อย่างเดียว — ยกเลิกบิลทำที่หน้าขาย (F4) ซึ่งต้องใช้ PIN เภสัชกร"""

    list_display = ("number", "created_at", "buyer_display", "total", "payment_method", "status", "cashier")
    list_filter = ("status", "payment_method", "created_at")
    search_fields = ("number", "buyer_name", "customer__name")
    date_hierarchy = "created_at"
    inlines = [SaleItemInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
