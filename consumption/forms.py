from django import forms

from .models import MeterReading, TariffBand, WaterBill, WaterMeter


class WaterMeterForm(forms.ModelForm):
    class Meta:
        model = WaterMeter
        fields = ("zone", "serial_number", "customer_category", "installed_on", "active", "horizon_days")
        widgets = {"installed_on": forms.DateInput(attrs={"type": "date"})}


class MeterReadingForm(forms.ModelForm):
    class Meta:
        model = MeterReading
        fields = ("meter", "recorded_at", "index_m3", "source")
        widgets = {"recorded_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class TariffBandForm(forms.ModelForm):
    class Meta:
        model = TariffBand
        fields = "__all__"
        widgets = {"valid_from": forms.DateInput(attrs={"type": "date"}), "valid_until": forms.DateInput(attrs={"type": "date"})}


class WaterBillForm(forms.ModelForm):
    class Meta:
        model = WaterBill
        fields = ("meter", "sonede_band", "onas_band", "period_start", "period_end", "volume_m3")
        widgets = {"period_start": forms.DateInput(attrs={"type": "date"}), "period_end": forms.DateInput(attrs={"type": "date"})}
