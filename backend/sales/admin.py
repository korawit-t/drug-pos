from django.contrib import admin

from .models import Customer, CustomerAllergy, Sale, SaleItem


class CustomerAllergyInline(admin.TabularInline):
    model = CustomerAllergy
    extra = 1
    fields = ("allergen", "substance", "reaction", "severity")
    autocomplete_fields = ("allergen",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "price_level", "allergy_summary")
    list_filter = ("price_level",)
    search_fields = ("name", "phone")
    inlines = [CustomerAllergyInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("allergy_records__allergen")

    @admin.display(description="แพ้ยา")
    def allergy_summary(self, obj):
        return ", ".join(record.label for record in obj.allergy_records.all()) or "-"

    def save_formset(self, request, form, formset, change):
        for record in formset.save(commit=False):
            if record.pk is None:
                record.recorded_by = request.user
            record.save()
        for record in formset.deleted_objects:
            record.delete()
        formset.save_m2m()


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    fields = (
        "description", "qty", "unit_name", "unit_price", "line_total", "dosage_text", "confirmed_by",
        "allergy_alert", "allergy_note",
    )
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
