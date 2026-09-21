from django.contrib import admin
from django.urls import include, path

from core.views import spa

from .api import api

admin.site.site_header = "Drug POS — หลังร้าน"
admin.site.site_title = "Drug POS"
admin.site.index_title = "จัดการข้อมูลร้าน"
admin.site.site_url = "/"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("print/", include("sales.urls")),
    path("reports/", include("reports.urls")),
    path("", spa, name="pos"),
]
