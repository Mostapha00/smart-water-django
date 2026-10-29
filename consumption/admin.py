from django.contrib import admin

from .models import MeterReading, TariffBand, WaterBill, WaterMeter


@admin.register(WaterMeter)
class WaterMeterAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "zone", "customer_category", "active", "forecast_m3", "predicted_at")
    list_filter = ("active", "customer_category", "zone__site")
    search_fields = ("serial_number", "zone__code", "zone__site__name")
    readonly_fields = ("forecast_m3", "model_version", "predicted_at")


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ("meter", "recorded_at", "index_m3", "source", "anomaly_score")
    list_filter = ("source", "meter__zone__site")
    date_hierarchy = "recorded_at"


@admin.register(TariffBand)
class TariffBandAdmin(admin.ModelAdmin):
    list_display = ("service", "customer_category", "valid_from", "valid_until", "lower_bound_m3", "upper_bound_m3", "price_per_m3_tnd")
    list_filter = ("service", "customer_category")


@admin.register(WaterBill)
class WaterBillAdmin(admin.ModelAdmin):
    list_display = ("meter", "period_start", "period_end", "volume_m3", "total_amount_tnd")
    list_filter = ("period_start", "meter__zone__site")
    date_hierarchy = "period_end"
