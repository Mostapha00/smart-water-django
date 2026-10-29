"""Student 2: cumulative readings, configurable tariffs, and traceable bills."""
from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

ZERO = Decimal("0")


def bill_reference():
    return f"BILL-{uuid4().hex[:12].upper()}"


def midnight(day):
    """Billing intervals run between exact local-midnight indexes, end exclusive."""
    return timezone.make_aware(datetime.combine(day, time.min))


class WaterMeter(models.Model):
    zone = models.ForeignKey("infrastructure.WaterZone", on_delete=models.PROTECT, related_name="meters")
    serial_number = models.CharField(max_length=64, unique=True)
    customer_category = models.CharField(max_length=80)
    installed_on = models.DateField()
    active = models.BooleanField(default=True)
    forecast_m3 = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(ZERO)])
    horizon_days = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(365)])
    model_version = models.CharField(max_length=100, blank=True)
    predicted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["serial_number"]

    def __str__(self):
        return self.serial_number

    def get_absolute_url(self):
        return reverse("consumption:meter_detail", args=[self.pk])

    def clean(self):
        super().clean()
        if self.pk and isinstance(self.installed_on, date):
            if self.readings.filter(recorded_at__lt=midnight(self.installed_on)).exists():
                raise ValidationError({"installed_on": "Installation cannot be after an existing reading."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def forecast_consumption(self, horizon_days=30):
        """Persist a versioned forecast and return its calculation and tariff alerts."""
        from .services.forecasting import forecast_meter
        return forecast_meter(self, horizon_days)

    def import_csv_readings(self, file):
        """Import a UTF-8 CSV atomically; identical rows are safe to import again."""
        from .services.readings import import_readings
        return import_readings(self, file)

    def volume_between(self, start, end):
        """Return consumption and real boundary readings; never interpolate a bill."""
        if end <= start:
            raise ValidationError("The end date must be after the start date.")
        rows = {r.recorded_at: r for r in self.readings.filter(recorded_at__in=[midnight(start), midnight(end)])}
        first, last = rows.get(midnight(start)), rows.get(midnight(end))
        if first is None or last is None:
            raise ValidationError("Billing requires a reading at local midnight on both boundary dates.")
        return last.index_m3 - first.index_m3, first, last


class MeterReading(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        CSV = "csv", "CSV import"

    meter = models.ForeignKey(WaterMeter, on_delete=models.CASCADE, related_name="readings")
    recorded_at = models.DateTimeField()
    index_m3 = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(ZERO)])
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    # Student 3 owns anomaly inference; these fields preserve its integration contract.
    anomaly_score = models.FloatField(null=True, blank=True)
    model_version = models.CharField(max_length=100, blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["recorded_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["meter", "recorded_at"], name="consumption_unique_reading"),
            models.CheckConstraint(condition=Q(index_m3__gte=0), name="consumption_nonnegative_index"),
        ]

    def __str__(self):
        return f"{self.meter}: {self.index_m3} m³ at {self.recorded_at}"

    def get_absolute_url(self):
        return reverse("consumption:reading_detail", args=[self.pk])

    def _check_issued_bills(self):
        dates = [timezone.localdate(self.recorded_at)]
        if self.pk:
            dates.append(timezone.localdate(type(self).objects.get(pk=self.pk).recorded_at))
        for day in dates:
            if WaterBill.objects.filter(meter_id=self.meter_id, issued_at__isnull=False, period_start__lte=day, period_end__gte=day).exists():
                raise ValidationError("Readings covered by an issued bill cannot be changed or deleted.")

    def clean(self):
        super().clean()
        if not self.meter_id or not isinstance(self.recorded_at, datetime) or not isinstance(self.index_m3, Decimal):
            return  # Field validation reports missing or malformed values.
        meter = WaterMeter.objects.filter(pk=self.meter_id).first()
        if meter is None:
            return  # Foreign-key validation reports the missing parent.
        if self.pk and type(self).objects.filter(pk=self.pk).exclude(meter_id=self.meter_id).exists():
            raise ValidationError({"meter": "A reading cannot be moved to a different meter."})
        if timezone.localdate(self.recorded_at) < meter.installed_on:
            raise ValidationError({"recorded_at": "A reading cannot predate installation."})
        others = meter.readings.exclude(pk=self.pk)
        before = others.filter(recorded_at__lt=self.recorded_at).order_by("-recorded_at").first()
        after = others.filter(recorded_at__gt=self.recorded_at).order_by("recorded_at").first()
        if (before and before.index_m3 > self.index_m3) or (after and after.index_m3 < self.index_m3):
            raise ValidationError({"index_m3": "Cumulative indexes must not decrease over time."})
        self._check_issued_bills()

    def save(self, *args, **kwargs):
        with transaction.atomic():
            self.full_clean()
            WaterMeter.objects.select_for_update().get(pk=self.meter_id)
            self.clean()  # Recheck chronological neighbours after acquiring the lock.
            result = super().save(*args, **kwargs)
            invalidate_forecast(self.meter_id)
            return result

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            WaterMeter.objects.select_for_update().get(pk=self.meter_id)
            self._check_issued_bills()
            result = super().delete(*args, **kwargs)
            invalidate_forecast(self.meter_id)
            return result

    def calculate_volume(self):
        """Return the increment from the previous index, or None for the first one."""
        before = self.meter.readings.filter(recorded_at__lt=self.recorded_at).order_by("-recorded_at").first()
        return self.index_m3 - before.index_m3 if before else None

    def detect_anomaly(self):
        """Integration point owned by Student 3; no invented ML score is stored."""
        raise NotImplementedError("Anomaly detection belongs to the quality_leaks module.")


def invalidate_forecast(meter_id):
    WaterMeter.objects.filter(pk=meter_id).update(forecast_m3=None, horizon_days=None, model_version="", predicted_at=None)


class TariffBand(models.Model):
    class Service(models.TextChoices):
        SONEDE = "SONEDE", "SONEDE"
        ONAS = "ONAS", "ONAS"

    class Mode(models.TextChoices):
        GLOBAL = "global", "Whole-volume rate"
        MARGINAL = "marginal", "Marginal bands"

    service = models.CharField(max_length=6, choices=Service.choices)
    customer_category = models.CharField(max_length=80)
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    lower_bound_m3 = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(ZERO)])
    upper_bound_m3 = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(ZERO)])
    price_per_m3_tnd = models.DecimalField(max_digits=10, decimal_places=4, validators=[MinValueValidator(ZERO)])
    fixed_fee_tnd = models.DecimalField(max_digits=12, decimal_places=3, default=ZERO, validators=[MinValueValidator(ZERO)])
    reference_period_days = models.PositiveSmallIntegerField(default=90, validators=[MinValueValidator(1)])
    calculation_mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.GLOBAL)
    official_source = models.URLField(max_length=500, help_text="Configuration source. Example tariffs must be labelled as examples.")

    class Meta:
        ordering = ["service", "customer_category", "valid_from", "lower_bound_m3"]
        constraints = [
            models.CheckConstraint(condition=Q(upper_bound_m3__isnull=True) | Q(upper_bound_m3__gt=F("lower_bound_m3")), name="consumption_tariff_bounds"),
            models.CheckConstraint(condition=Q(valid_until__isnull=True) | Q(valid_until__gte=F("valid_from")), name="consumption_tariff_dates"),
            models.CheckConstraint(condition=Q(lower_bound_m3__gte=0, price_per_m3_tnd__gte=0, fixed_fee_tnd__gte=0, reference_period_days__gt=0), name="consumption_tariff_nonnegative"),
        ]

    def __str__(self):
        return f"{self.service} / {self.customer_category}: {self.lower_bound_m3}–{self.upper_bound_m3 or '∞'} m³"

    def get_absolute_url(self):
        return reverse("consumption:tariff_detail", args=[self.pk])

    def clean(self):
        super().clean()
        if not isinstance(self.valid_from, date) or not isinstance(self.lower_bound_m3, Decimal):
            return
        if self.upper_bound_m3 is not None and not isinstance(self.upper_bound_m3, Decimal):
            return
        if self.valid_until is not None and not isinstance(self.valid_until, date):
            return
        qs = type(self).objects.filter(service=self.service, customer_category=self.customer_category).exclude(pk=self.pk)
        qs = qs.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=self.valid_from))
        if self.valid_until:
            qs = qs.filter(valid_from__lte=self.valid_until)
        qs = qs.filter(Q(upper_bound_m3__isnull=True) | Q(upper_bound_m3__gt=self.lower_bound_m3))
        if self.upper_bound_m3 is not None:
            qs = qs.filter(lower_bound_m3__lt=self.upper_bound_m3)
        if qs.exists():
            raise ValidationError("This tariff overlaps an existing band for the same service, category, and validity period.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def calculate_variable_charge(self, volume_m3, days=None):
        """Calculate this band's variable component, excluding its fixed fee."""
        days = self.reference_period_days if days is None else days
        factor = Decimal(days) / self.reference_period_days
        low = self.lower_bound_m3 * factor
        high = self.upper_bound_m3 * factor if self.upper_bound_m3 is not None else None
        if self.calculation_mode == self.Mode.GLOBAL:
            if volume_m3 < low or (high is not None and volume_m3 >= high):
                raise ValidationError("The volume does not belong to this whole-volume tariff band.")
            return volume_m3 * self.price_per_m3_tnd
        return max(ZERO, min(volume_m3, high) - low if high is not None else volume_m3 - low) * self.price_per_m3_tnd


class BillQuerySet(models.QuerySet):
    def delete(self):
        if self.filter(issued_at__isnull=False).exists():
            raise ValidationError("Issued bills cannot be deleted.")
        return super().delete()


class WaterBill(models.Model):
    meter = models.ForeignKey(WaterMeter, on_delete=models.PROTECT, related_name="bills")
    sonede_band = models.ForeignKey(TariffBand, on_delete=models.PROTECT, related_name="sonede_bills")
    onas_band = models.ForeignKey(TariffBand, on_delete=models.PROTECT, null=True, blank=True, related_name="onas_bills")
    reference = models.CharField(max_length=40, unique=True, default=bill_reference, editable=False)
    period_start = models.DateField()
    period_end = models.DateField(help_text="Exclusive end; exact midnight readings are required at both boundaries.")
    include_onas = models.BooleanField(default=True)
    volume_m3 = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(ZERO)])
    sonede_amount_tnd = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(ZERO)])
    onas_amount_tnd = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(ZERO)])
    total_tnd = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(ZERO)])
    tariff_snapshot = models.JSONField(default=dict)
    issued_at = models.DateTimeField(null=True, blank=True, editable=False)
    objects = BillQuerySet.as_manager()

    class Meta:
        ordering = ["-period_end", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["meter", "period_start", "period_end"], name="consumption_unique_bill_period"),
            models.CheckConstraint(condition=Q(period_end__gt=F("period_start")), name="consumption_bill_dates"),
            models.CheckConstraint(condition=Q(volume_m3__gte=0, sonede_amount_tnd__gte=0, onas_amount_tnd__gte=0, total_tnd__gte=0), name="consumption_bill_nonnegative"),
        ]

    def __str__(self):
        return self.reference

    def get_absolute_url(self):
        return reverse("consumption:bill_detail", args=[self.pk])

    def clean(self):
        super().clean()
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if old.issued_at and any(getattr(self, f.attname) != getattr(old, f.attname) for f in self._meta.concrete_fields):
                raise ValidationError("An issued bill is immutable.")
        if isinstance(self.period_start, date) and isinstance(self.period_end, date):
            if type(self).objects.filter(meter_id=self.meter_id, issued_at__isnull=False, period_start__lt=self.period_end, period_end__gt=self.period_start).exclude(pk=self.pk).exists():
                raise ValidationError("The period overlaps an issued bill.")
        if self.sonede_band_id and self.sonede_band.service != TariffBand.Service.SONEDE:
            raise ValidationError({"sonede_band": "A SONEDE band is required."})
        if self.onas_band_id and self.onas_band.service != TariffBand.Service.ONAS:
            raise ValidationError({"onas_band": "An ONAS band is required."})
        amounts = (self.sonede_amount_tnd, self.onas_amount_tnd, self.total_tnd)
        if all(isinstance(v, Decimal) for v in amounts) and self.total_tnd != self.sonede_amount_tnd + self.onas_amount_tnd:
            raise ValidationError({"total_tnd": "The total must equal SONEDE plus ONAS."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.issued_at:
            raise ValidationError("Issued bills cannot be deleted.")
        return super().delete(*args, **kwargs)

    def calculate_amounts(self):
        """Recalculate a draft from real indexes and save the tariff snapshot."""
        from .services.billing import recalculate_bill
        return recalculate_bill(self)

    def issue_bill(self):
        """Recalculate and freeze a bill atomically; issuing twice is idempotent."""
        from .services.billing import issue_bill
        return issue_bill(self)