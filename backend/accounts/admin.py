from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.utils import timezone

from .models import PinAttempt, User


class UserCreateForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User


class UserEditForm(UserChangeForm):
    new_pin = forms.CharField(
        label="ตั้ง PIN ใหม่",
        required=False,
        min_length=4,
        max_length=6,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "new-password"}),
        help_text="ตัวเลข 4–6 หลัก ใช้ยืนยันการจ่ายยาและยกเลิกบิล — เว้นว่างถ้าไม่เปลี่ยน",
    )

    class Meta(UserChangeForm.Meta):
        model = User

    def clean_new_pin(self):
        pin = self.cleaned_data.get("new_pin", "")
        if pin and not pin.isdigit():
            raise forms.ValidationError("PIN ต้องเป็นตัวเลขเท่านั้น")
        return pin


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserEditForm
    add_form = UserCreateForm
    list_display = ("username", "display_name", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    readonly_fields = ("pin_status",)
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("ร้านยา", {"fields": ("role", "display_name", "license_no", "new_pin", "pin_status")}),
    )

    @admin.display(description="สถานะ PIN")
    def pin_status(self, obj):
        if not obj.pin_hash:
            return "ยังไม่ได้ตั้ง"
        if obj.pin_locked_until and obj.pin_locked_until > timezone.now():
            return f"ล็อกถึง {timezone.localtime(obj.pin_locked_until):%H:%M}"
        return "ตั้งแล้ว"

    def save_model(self, request, obj, form, change):
        if pin := form.cleaned_data.get("new_pin"):
            obj.set_pin(pin)
        super().save_model(request, obj, form, change)


@admin.register(PinAttempt)
class PinAttemptAdmin(admin.ModelAdmin):
    list_display = ("created_at", "pharmacist", "action", "success", "requested_by", "terminal", "detail")
    list_filter = ("action", "success", "pharmacist")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
