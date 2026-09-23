from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="reports"),
    path("ky9/", views.ky9, name="report-ky9"),
    path("ky11/", views.ky11, name="report-ky11"),
    path("expiry/", views.expiry, name="report-expiry"),
    path("adjustments/", views.adjustments, name="report-adjustments"),
]
