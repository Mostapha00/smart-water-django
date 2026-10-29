"""Models and small domain services for water consumption and billing."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone


class WaterMeter(models.Model):
    class CustomerCategory(models.TextChoices):
        HOUSEHOLD = "household", "Ménage"
        COMMERCIAL = "commercial", "Commercial"
        INDUSTRIAL = "industrial", "Industriel"
        PUBLIC = "public", "Service public"

    zone = models.ForeignKey("infrastructure.WaterZone", on_delete=models.PROTECT, related_name="water_meters")
    serial_number = models.CharField(max_length=60, unique=True)
    customer_category = models.CharField(max_length=20, choices=CustomerCategory.choices, default=CustomerCategory.PUBLIC)
    installed_on = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    forecast_m3 = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                       validators=[MinValueValidator(Decimal("0"))])
    horizon_days = models.PositiveIntegerField(default=30)
    model_version = models.CharField(max_length=40, blank=True)
    predicted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["serial_number"]

    def __str__(self):
        return self.serial_number

    def clean(self):
        super().clean()
        if self.installed_on and self.installed_on > timezone.localdate():
            raise ValidationError({"installed_on": "La date d'installation ne peut pas être future."})
        if self.horizon_days < 1:
            raise ValidationError({"horizon_days": "L'horizon doit être positif."})

    def forecast_consumption(self, horizon_days=None, save=True):
        """Forecast volume using the average daily rate of consecutive indexes."""
        horizon = int(horizon_days or self.horizon_days)
        if horizon < 1:
            raise ValueError("horizon_days must be positive")
        readings = list(self.readings.order_by("recorded_at", "pk"))
        rates = []
        for previous, current in zip(readings, readings[1:]):
            days = Decimal(str((current.recorded_at - previous.recorded_at).total_seconds())) / Decimal("86400")
            volume = current.index_m3 - previous.index_m3
            if days > 0 and volume >= 0:
                rates.append(volume / days)
        if not rates:
            return None
        prediction = (sum(rates, Decimal("0")) / len(rates) * horizon).quantize(Decimal("0.001"))
        self.forecast_m3 = prediction
        self.horizon_days = horizon
        self.model_version = "average-daily-1"
        self.predicted_at = timezone.now()
        if save and self.pk:
            self.save(update_fields=["forecast_m3", "horizon_days", "model_version", "predicted_at"])
        return prediction

    def import_csv_readings(self, csv_file, source="csv", replace=False):
        """Import ``recorded_at,index_m3`` rows and return created readings."""
        if hasattr(csv_file, "read"):
            content = csv_file.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8-sig")
        else:
            content = str(csv_file)
        rows = csv.DictReader(io.StringIO(content))
        names = {name.strip().lower() for name in (rows.fieldnames or []) if name}
        if not {"recorded_at", "index_m3"}.issubset(names):
            raise ValidationError("Le CSV doit contenir les colonnes recorded_at et index_m3.")
        imported = []
        with transaction.atomic():
            if replace:
                self.readings.all().delete()
            for row in rows:
                normalized = {str(k).strip().lower(): v for k, v in row.items()}
                try:
                    recorded_at = datetime.fromisoformat(normalized["recorded_at"].strip())
                    if timezone.is_naive(recorded_at):
                        recorded_at = timezone.make_aware(recorded_at)
                    index = Decimal(normalized["index_m3"].strip())
                except (KeyError, ValueError, InvalidOperation) as exc:
                    raise ValidationError(f"Relevé CSV invalide : {row}") from exc
                if index < 0:
                    raise ValidationError("Un index de compteur ne peut pas être négatif.")
                imported.append(self.readings.create(recorded_at=recorded_at, index_m3=index, source=source))
        return imported


class MeterReading(models.Model):
    meter = models.ForeignKey(WaterMeter, on_delete=models.CASCADE, related_name="readings")
    recorded_at = models.DateTimeField()
    index_m3 = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    source = models.CharField(max_length=30, default="manual")
    anomaly_score = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    model_version = models.CharField(max_length=40, blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["recorded_at", "pk"]
        constraints = [models.UniqueConstraint(fields=["meter", "recorded_at"], name="unique_meter_reading_time")]

    def __str__(self):
        return f"{self.meter} · {self.recorded_at:%Y-%m-%d}"

    def clean(self):
        super().clean()
        if self.meter_id:
            previous = self.meter.readings.filter(recorded_at__lt=self.recorded_at).order_by("-recorded_at").first()
            if previous and self.index_m3 < previous.index_m3:
                raise ValidationError({"index_m3": "L'index cumulé doit être croissant."})

    def calculate_volume(self, previous=None):
        if previous is None:
            previous = self.meter.readings.filter(recorded_at__lt=self.recorded_at).order_by("-recorded_at").first()
        if previous is None:
            return None
        volume = self.index_m3 - previous.index_m3
        if volume < 0:
            raise ValidationError("L'index cumulé est inférieur au relevé précédent.")
        return volume

    def detect_anomaly(self, window=3, threshold=Decimal("1.4"), save=True):
        volume = self.calculate_volume()
        if volume is None:
            return False
        previous = list(self.meter.readings.filter(recorded_at__lt=self.recorded_at).order_by("-recorded_at")[:window + 1])
        volumes = [r.calculate_volume() for r in previous]
        volumes = [v for v in volumes if v is not None and v >= 0]
        average = sum(volumes, Decimal("0")) / len(volumes) if volumes else Decimal("0")
        score = (volume / average) if average else Decimal("0")
        anomalous = bool(average and score > Decimal(str(threshold)))
        self.anomaly_score = score.quantize(Decimal("0.001")) if average else Decimal("0")
        self.model_version = "rolling-ratio-1"
        self.analyzed_at = timezone.now()
        if save and self.pk:
            self.save(update_fields=["anomaly_score", "model_version", "analyzed_at"])
        return anomalous


class TariffBand(models.Model):
    class Service(models.TextChoices):
        SONEDE = "SONEDE", "SONEDE"
        ONAS = "ONAS", "ONAS"

    service = models.CharField(max_length=10, choices=Service.choices)
    customer_category = models.CharField(max_length=20, choices=WaterMeter.CustomerCategory.choices)
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    lower_bound_m3 = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    upper_bound_m3 = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                          validators=[MinValueValidator(Decimal("0"))])
    price_per_m3_tnd = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    fixed_fee_tnd = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal("0"),
                                        validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        ordering = ["service", "customer_category", "valid_from", "lower_bound_m3"]

    def clean(self):
        super().clean()
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "La fin doit être postérieure au début."})
        if self.upper_bound_m3 is not None and self.upper_bound_m3 <= self.lower_bound_m3:
            raise ValidationError({"upper_bound_m3": "La borne supérieure doit être strictement supérieure."})

    def charge(self, volume):
        volume = Decimal(str(volume))
        if volume < self.lower_bound_m3:
            return Decimal("0")
        billable = volume - self.lower_bound_m3
        if self.upper_bound_m3 is not None:
            billable = min(billable, self.upper_bound_m3 - self.lower_bound_m3)
        price = Decimal(str(self.price_per_m3_tnd))
        return (billable * price).quantize(Decimal("0.001"))


class WaterBill(models.Model):
    meter = models.ForeignKey(WaterMeter, on_delete=models.PROTECT, related_name="bills")
    sonede_band = models.ForeignKey(TariffBand, on_delete=models.PROTECT, related_name="sonede_bills",
                                    null=True, blank=True, limit_choices_to={"service": "SONEDE"})
    onas_band = models.ForeignKey(TariffBand, on_delete=models.PROTECT, related_name="onas_bills",
                                  null=True, blank=True, limit_choices_to={"service": "ONAS"})
    period_start = models.DateField()
    period_end = models.DateField()
    volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    sonede_amount_tnd = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    onas_amount_tnd = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    total_amount_tnd = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    tariff_snapshot = models.JSONField(default=dict, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end"]
        constraints = [models.UniqueConstraint(fields=["meter", "period_start", "period_end"], name="unique_meter_bill_period")]

    def clean(self):
        super().clean()
        if self.period_end < self.period_start:
            raise ValidationError({"period_end": "La fin de période doit être postérieure au début."})
        for band in (self.sonede_band, self.onas_band):
            if band and band.customer_category != self.meter.customer_category:
                raise ValidationError("La catégorie du tarif doit correspondre au compteur.")

    def calculate_amounts(self, save=True):
        values = {}
        for name, band in (("sonede_amount_tnd", self.sonede_band), ("onas_amount_tnd", self.onas_band)):
            values[name] = (band.charge(self.volume_m3) + Decimal(str(band.fixed_fee_tnd))) if band else Decimal("0")
        values["total_amount_tnd"] = values["sonede_amount_tnd"] + values["onas_amount_tnd"]
        self.sonede_amount_tnd = values["sonede_amount_tnd"]
        self.onas_amount_tnd = values["onas_amount_tnd"]
        self.total_amount_tnd = values["total_amount_tnd"]
        self.tariff_snapshot = {
            key: {"service": band.service,
                  "price_per_m3_tnd": format(Decimal(str(band.price_per_m3_tnd)), ".3f"),
                  "fixed_fee_tnd": format(Decimal(str(band.fixed_fee_tnd)), ".3f")} for key, band in
            (("sonede", self.sonede_band), ("onas", self.onas_band)) if band
        }
        if save and self.pk:
            self.save(update_fields=["sonede_amount_tnd", "onas_amount_tnd", "total_amount_tnd", "tariff_snapshot"])
        return self.total_amount_tnd
