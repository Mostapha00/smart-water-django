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
        """Forecast volume: trained LightGBM model when available, else the average daily rate."""
        from .services.forecasting import predict

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
        learned = predict(self, horizon)
        if learned is not None:
            prediction, version = Decimal(str(learned[0])).quantize(Decimal("0.001")), learned[1]
        else:
            prediction, version = (sum(rates, Decimal("0")) / len(rates) * horizon).quantize(Decimal("0.001")), "average-daily-1"
        self.forecast_m3 = prediction
        self.horizon_days = horizon
        self.model_version = version
        self.predicted_at = timezone.now()
        if save and self.pk:
            self.save(update_fields=["forecast_m3", "horizon_days", "model_version", "predicted_at"])
        return prediction

    def import_csv_readings(self, csv_file, source="csv", replace=False):
        """Import ``recorded_at,index_m3`` rows atomically and return the created readings.

        Rows identical to an existing reading are skipped, so the same file can be imported twice.
        A different index at an existing date, a negative or decreasing index, or a malformed row
        rejects the whole file: nothing is imported.
        """
        if hasattr(csv_file, "read"):
            content = csv_file.read()
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8-sig")
                except UnicodeDecodeError as exc:
                    raise ValidationError("Le fichier doit être un CSV encodé en UTF-8.") from exc
        else:
            content = str(csv_file)
        rows = csv.DictReader(io.StringIO(content))
        names = {name.strip().lower() for name in (rows.fieldnames or []) if name}
        if not {"recorded_at", "index_m3"}.issubset(names):
            raise ValidationError("Le CSV doit contenir les colonnes recorded_at et index_m3.")
        parsed = {}
        for line, row in enumerate(rows, start=2):
            normalized = {str(k).strip().lower(): v for k, v in row.items() if k}
            try:
                recorded_at = datetime.fromisoformat((normalized["recorded_at"] or "").strip())
                if timezone.is_naive(recorded_at):
                    recorded_at = timezone.make_aware(recorded_at)
                index = Decimal((normalized["index_m3"] or "").strip())
            except (KeyError, ValueError, InvalidOperation, AttributeError) as exc:
                raise ValidationError(f"Ligne {line} invalide : date ISO et index numérique attendus.") from exc
            if not index.is_finite() or index < 0:
                raise ValidationError(f"Ligne {line} : un index de compteur doit être un nombre positif.")
            if parsed.get(recorded_at, index) != index:
                raise ValidationError(f"Ligne {line} : deux index différents pour la même date.")
            parsed[recorded_at] = index
        if not parsed:
            raise ValidationError("Le CSV ne contient aucun relevé.")
        with transaction.atomic():
            if replace:
                self.readings.all().delete()
            existing = dict(self.readings.values_list("recorded_at", "index_m3"))
            for when, index in parsed.items():
                if when in existing and existing[when] != index:
                    raise ValidationError(f"Le relevé du {when:%d/%m/%Y %H:%M} existe déjà avec un autre index.")
            combined = sorted({**existing, **parsed}.items())
            if any(later[1] < earlier[1] for earlier, later in zip(combined, combined[1:])):
                raise ValidationError("L'index cumulé doit augmenter avec le temps : rien n'a été importé.")
            return [self.readings.create(recorded_at=when, index_m3=index, source=source)
                    for when, index in sorted(parsed.items()) if when not in existing]

    def index_at(self, when):
        """Dernier relevé enregistré à la date `when` ou avant (None s'il n'y en a pas)."""
        return self.readings.filter(recorded_at__lte=when).order_by("-recorded_at", "-pk").first()

    def volume_between(self, start, end):
        """Volume consommé entre deux instants, d'après les relevés réels (sans interpolation).

        Utilise le dernier relevé avant chaque borne (ou le premier relevé de la période si le compteur
        a été posé après `start`). Renvoie (volume_m3, premier_relevé, dernier_relevé) ou None si la
        période ne contient pas deux relevés distincts.
        """
        first = self.index_at(start) or self.readings.filter(recorded_at__gte=start, recorded_at__lte=end).order_by("recorded_at", "pk").first()
        last = self.index_at(end)
        if first is None or last is None or last.recorded_at <= first.recorded_at:
            return None
        return last.index_m3 - first.index_m3, first, last


class MeterReading(models.Model):
    meter = models.ForeignKey(WaterMeter, on_delete=models.CASCADE, related_name="readings")
    recorded_at = models.DateTimeField()
    index_m3 = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    source = models.CharField(max_length=30, default="manual")
    anomaly_score = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    is_anomaly = models.BooleanField("fuite possible", null=True, blank=True,
                                     help_text="Consommation atypique et supérieure à l'habitude du compteur. Vide = non analysé.")
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

    def detect_anomaly(self, save=True):
        """Possible leak? Isolation Forest over all meters when there is enough data, else a simple rule.

        See consumption/services/anomaly.py. Returns True when this reading is flagged.
        """
        from .services.anomaly import analyze, rule_flag

        if not save or not self.pk:
            return rule_flag(self, save=False)
        analyze([self.meter])  # scores every reading of this meter in one pass
        self.refresh_from_db(fields=["anomaly_score", "is_anomaly", "model_version", "analyzed_at"])
        return bool(self.is_anomaly)


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
