from datetime import datetime, time

from django import forms
from django.utils import timezone

from .models import MeterReading, TariffBand, WaterBill, WaterMeter

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class WaterMeterForm(forms.ModelForm):
    class Meta:
        model = WaterMeter
        fields = ("zone", "serial_number", "customer_category", "installed_on", "active", "horizon_days")
        widgets = {"installed_on": DATE}
        labels = {"zone": "Zone", "serial_number": "Numéro de série", "customer_category": "Catégorie d'abonné",
                  "installed_on": "Posé le", "active": "Actif", "horizon_days": "Horizon de prévision (jours)"}


class MeterReadingForm(forms.ModelForm):
    class Meta:
        model = MeterReading
        fields = ("meter", "recorded_at", "index_m3", "source")
        widgets = {"recorded_at": DATETIME}
        labels = {"meter": "Compteur", "recorded_at": "Date du relevé", "index_m3": "Index cumulé (m³)", "source": "Source"}
        help_texts = {"index_m3": "Valeur affichée par le compteur (cumulée), pas la consommation de la période."}


class TariffBandForm(forms.ModelForm):
    class Meta:
        model = TariffBand
        fields = "__all__"
        widgets = {"valid_from": DATE, "valid_until": DATE}
        labels = {"service": "Service", "customer_category": "Catégorie d'abonné", "valid_from": "Valable du",
                  "valid_until": "Valable jusqu'au", "lower_bound_m3": "Tranche : de (m³)", "upper_bound_m3": "Tranche : à (m³)",
                  "price_per_m3_tnd": "Prix (TND/m³)", "fixed_fee_tnd": "Redevance fixe (TND)"}


class WaterBillForm(forms.ModelForm):
    class Meta:
        model = WaterBill
        fields = ("meter", "sonede_band", "onas_band", "period_start", "period_end", "volume_m3")
        widgets = {"period_start": DATE, "period_end": DATE}
        labels = {"meter": "Compteur", "sonede_band": "Tranche SONEDE", "onas_band": "Tranche ONAS",
                  "period_start": "Début de période", "period_end": "Fin de période", "volume_m3": "Volume (m³)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["volume_m3"].required = False
        self.fields["volume_m3"].help_text = "Laisser vide : calculé à partir des relevés du compteur sur la période."

    def clean(self):
        data = super().clean()
        meter, start, end = data.get("meter"), data.get("period_start"), data.get("period_end")
        if data.get("volume_m3") is None and meter and start and end and not self.errors:
            tz = timezone.get_current_timezone()
            result = meter.volume_between(datetime.combine(start, time.min, tz), datetime.combine(end, time.max, tz))
            if result is None:
                self.add_error("volume_m3", "Pas assez de relevés sur cette période pour calculer le volume : saisissez-le.")
            else:
                data["volume_m3"] = result[0]
                self.instance.volume_m3 = result[0]
        return data
