from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("student", "paid_on", "amount_rub", "note")
    list_filter = ("paid_on",)
