from django.urls import path

from .views import (
    dashboard, finance_export, finance_export_csv, finance_import,
    opening_balance, payment_detail, payments_collection,
)


urlpatterns = [
    path("", dashboard),
    path("payments", payments_collection),
    path("payments/<uuid:payment_id>", payment_detail),
    path("students/<uuid:student_id>/opening-balance", opening_balance),
    path("export", finance_export),
    path("export/csv", finance_export_csv),
    path("import", finance_import),
]
