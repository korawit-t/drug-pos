from django.urls import path

from . import views

urlpatterns = [
    path("receipt/<int:sale_id>/", views.receipt, name="print-receipt"),
    path("labels/<int:sale_id>/", views.labels, name="print-labels"),
]
