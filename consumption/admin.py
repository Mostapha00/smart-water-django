from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import MeterReading, TariffBand, WaterBill, WaterMeter


@admin.register(WaterMeter)
class WaterMeterAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "zone", "customer_category", "active", "forecast_m3", "model_version")
    list_filter = ("active", "customer_category", "zone__site")
    search_fields = ("serial_number", "zone__name", "zone__site__name")
    readonly_fields = ("forecast_m3", "horizon_days", "model_version", "predicted_at")


@admin.register(MeterReading)
class MeterReadingAdmin(admin.ModelAdmin):
    list_display = ("meter", "recorded_at", "index_m3", "source")
    list_filter = ("source", "meter__zone__site")
    search_fields = ("meter__serial_number",)
    readonly_fields = ("anomaly_score", "model_version", "analyzed_at")
    date_hierarchy = "recorded_at"
    # Delete each object through its issued-bill protection and forecast invalidation.
    actions = None

    def has_delete_permission(self, request, obj=None):
        if obj is not None:
            try:
                obj._check_issued_bills()
            except ValidationError:
                return False
        return super().has_delete_permission(request, obj)


@admin.register(TariffBand)
class TariffBandAdmin(admin.ModelAdmin):
    list_display = ("service", "customer_category", "valid_from", "valid_until", "lower_bound_m3", "upper_bound_m3", "price_per_m3_tnd", "calculation_mode")
    list_filter = ("service", "customer_category", "calculation_mode")
    search_fields = ("customer_category", "official_source")


class BillForm(forms.ModelForm):
    class Meta:
        model = WaterBill
        fields = ("meter", "period_start", "period_end", "include_onas")

    def clean(self):
        values = super().clean()
        if not self.errors:
            from .services.billing import _calculate
            for key, value in values.items():
                setattr(self.instance, key, value)
            _calculate(self.instance)
        return values


@admin.action(description="Issue selected draft bills")
def issue_selected(modeladmin, request, queryset):
    for bill in queryset:
        try:
            bill.issue_bill()
        except ValidationError as exc:
            modeladmin.message_user(request, f"{bill}: {' '.join(exc.messages)}", messages.ERROR)


@admin.register(WaterBill)
class WaterBillAdmin(admin.ModelAdmin):
    form = BillForm
    list_display = ("reference", "meter", "period_start", "period_end", "total_tnd", "issued_at")
    list_filter = ("issued_at", "meter__zone__site")
    search_fields = ("reference", "meter__serial_number")
    readonly_fields = ("reference", "sonede_band", "onas_band", "volume_m3", "sonede_amount_tnd", "onas_amount_tnd", "total_tnd", "tariff_snapshot", "issued_at")
    actions = [issue_selected]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.issued_at:
            return tuple(field.name for field in self.model._meta.fields)
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return (obj is None or obj.issued_at is None) and super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return (obj is None or obj.issued_at is None) and super().has_change_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def delete_queryset(self, request, queryset):
        queryset.delete()

    def save_model(self, request, obj, form, change):
        obj.calculate_amounts()
