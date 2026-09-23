from django import forms
from django.contrib import admin, messages
from django.db.models import OuterRef, Subquery, Sum
from django.utils import timezone
from django.utils.html import format_html

from core.models import ShopSettings
from core.thai import thai_date

from .allergy import AllergyIndex
from .models import Allergen, Lot, PriceLevel, Product, ProductUnit, Purchase, PurchaseItem, StockMovement, Supplier
from .services import StockError, post_purchase


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PriceLevel)
class PriceLevelAdmin(admin.ModelAdmin):
    list_display = ("level", "name")
    list_editable = ("name",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Allergen)
class AllergenAdmin(admin.ModelAdmin):
    list_display = ("name", "keywords", "related_groups")
    search_fields = ("name", "keywords")
    filter_horizontal = ("related",)

    @admin.display(description="อาจแพ้ข้ามกลุ่มกับ")
    def related_groups(self, obj):
        return ", ".join(group.name for group in obj.related.all()) or "-"


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "license_no")
    search_fields = ("name",)


PRICE_FIELDS = [f"price{level}" for level in range(1, 6)]


class ProductUnitForm(forms.ModelForm):
    class Meta:
        model = ProductUnit
        fields = ["name", "factor", "barcode", "is_default", *PRICE_FIELDS]
        widgets = {
            "name": forms.TextInput(attrs={"size": 8}),
            "factor": forms.NumberInput(attrs={"style": "width:5em"}),
            "barcode": forms.TextInput(attrs={"size": 14}),
            **{name: forms.NumberInput(attrs={"style": "width:6.5em", "step": "0.25"}) for name in PRICE_FIELDS},
        }


class ProductUnitInline(admin.TabularInline):
    model = ProductUnit
    form = ProductUnitForm
    extra = 1
    verbose_name_plural = "หน่วยขายและราคา (ราคาระดับ 2–5 เว้นว่างได้ — ถ้าว่างจะใช้ราคาระดับ 1)"

    def get_formset(self, request, obj=None, **kwargs):
        # Column headers show the shop's own price level names.
        formset = super().get_formset(request, obj, **kwargs)
        names = dict(PriceLevel.objects.values_list("level", "name"))
        for level in range(1, 6):
            if field := formset.form.base_fields.get(f"price{level}"):
                field.label = f"{level} · {names.get(level, '')}"
        return formset


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("trade_name", "strength", "generic_name", "category_badge", "in_ky11_list", "stock", "is_active")
    list_filter = ("category", "in_ky11_list", "in_ky13_list", "is_active")
    search_fields = ("trade_name", "generic_name", "units__barcode")
    inlines = [ProductUnitInline]
    fieldsets = (
        (None, {"fields": ("trade_name", "generic_name", "strength", "dosage_form", "base_unit", "is_active")}),
        ("ประเภทและบัญชี", {"fields": ("category", "in_ky11_list", "in_ky13_list", "registration_no", "tmt_code")}),
        ("ฉลากยาและการจัดเก็บ", {"fields": ("default_dosage", "label_warning", "storage_location")}),
        ("แจ้งเตือนแพ้ยา", {"fields": ("matched_allergens", "allergens")}),
    )
    filter_horizontal = ("allergens",)
    readonly_fields = ("matched_allergens",)

    @admin.display(description="กลุ่มยาที่ระบบจับคู่ได้ตอนนี้")
    def matched_allergens(self, obj):
        if obj.pk is None:
            return "บันทึกก่อนแล้วระบบจะแสดงกลุ่มที่จับคู่ได้"
        index = AllergyIndex()
        groups = index.product_groups(obj)
        return index.describe(groups) if groups else "ไม่เข้ากลุ่มใด — ถ้ายานี้อยู่ในกลุ่มที่แพ้บ่อย ให้เลือกเพิ่มด้านล่าง"

    def get_queryset(self, request):
        # A subquery, not a join: searching by barcode joins units, which would multiply a joined sum.
        sellable = (
            Lot.objects.filter(product=OuterRef("pk"), expiry_date__gte=timezone.localdate())
            .values("product")
            .annotate(total=Sum("qty_on_hand"))
            .values("total")
        )
        return super().get_queryset(request).annotate(_stock=Subquery(sellable))

    @admin.display(description="ประเภท", ordering="category")
    def category_badge(self, obj):
        return obj.get_category_display()

    @admin.display(description="คงเหลือ (ไม่รวมหมดอายุ)", ordering="_stock")
    def stock(self, obj):
        return f"{obj._stock or 0} {obj.base_unit}"


@admin.register(ProductUnit)
class ProductUnitAdmin(admin.ModelAdmin):
    """Not in the menu — exists so purchase lines can search units by name or barcode."""

    search_fields = ("product__trade_name", "product__generic_name", "barcode", "name")

    def get_model_perms(self, request):
        return {}


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 3
    autocomplete_fields = ("unit",)
    fields = ("unit", "qty", "lot_no", "expiry_date", "unit_cost")


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("received_date", "supplier", "invoice_no", "is_opening_balance", "status", "item_count")
    list_filter = ("status", "is_opening_balance", "supplier")
    date_hierarchy = "received_date"
    inlines = [PurchaseItemInline]
    actions = ["post_to_stock"]
    fields = ("is_opening_balance", "supplier", "invoice_no", "invoice_date", "received_date", "note", "status")
    readonly_fields = ("status",)

    @admin.display(description="จำนวนรายการ")
    def item_count(self, obj):
        return obj.items.count()

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        # A posted receipt is part of the stock ledger — view only.
        if obj is not None and obj.status == Purchase.Status.POSTED:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status == Purchase.Status.POSTED:
            return False
        return super().has_delete_permission(request, obj)

    @admin.action(description="บันทึกเข้าสต็อก")
    def post_to_stock(self, request, queryset):
        for purchase in queryset:
            try:
                post_purchase(purchase, request.user)
                self.message_user(request, f"บันทึกเข้าสต็อกแล้ว: {purchase}", messages.SUCCESS)
            except StockError as exc:
                self.message_user(request, f"{purchase}: {exc.message}", messages.ERROR)


@admin.register(Lot)
class LotAdmin(ReadOnlyAdmin):
    list_display = ("product", "lot_no", "expiry", "status", "qty_on_hand")
    list_filter = ("expiry_date",)
    search_fields = ("product__trade_name", "product__generic_name", "lot_no")

    @admin.display(description="วันหมดอายุ", ordering="expiry_date")
    def expiry(self, obj):
        return thai_date(obj.expiry_date)

    @admin.display(description="สถานะ")
    def status(self, obj):
        today = timezone.localdate()
        if obj.expiry_date < today:
            return format_html('<b style="color:{}">{}</b>', "#a32d2d", "หมดอายุแล้ว")
        if (obj.expiry_date - today).days <= ShopSettings.load().near_expiry_days:
            return format_html('<span style="color:{}">{}</span>', "#854f0b", "ใกล้หมดอายุ")
        return "ปกติ"


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "kind", "lot", "qty", "created_by", "note")
    list_filter = ("kind",)
    search_fields = ("lot__product__trade_name", "lot__lot_no", "note")
