"""Water quality measurements, alert rules, and leak investigations."""
from decimal import Decimal
import operator

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class WaterQualityTest(models.Model):
    zone = models.ForeignKey("infrastructure.WaterZone", on_delete=models.CASCADE, related_name="quality_tests")
    sampled_at = models.DateTimeField(default=timezone.now)
    laboratory = models.CharField(max_length=150, blank=True)
    ph = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(14)])
    turbidity_ntu = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    chlorine_mg_l = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])
    conductivity_us_cm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    potability_probability = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(1)])
    model_version = models.CharField(max_length=40, blank=True)
    predicted_at = models.DateTimeField(null=True, blank=True)

    def classify_potability(self, save=True):
        checks = []
        if self.ph is not None:
            checks.append(Decimal("1") if Decimal("6.5") <= self.ph <= Decimal("8.5") else Decimal("0"))
        if self.turbidity_ntu is not None:
            checks.append(Decimal("1") if self.turbidity_ntu <= Decimal("5") else Decimal("0"))
        if self.chlorine_mg_l is not None:
            checks.append(Decimal("1") if Decimal("0.2") <= self.chlorine_mg_l <= Decimal("0.5") else Decimal("0"))
        if self.conductivity_us_cm is not None:
            checks.append(Decimal("1") if self.conductivity_us_cm <= Decimal("2500") else Decimal("0"))
        self.potability_probability = (sum(checks, Decimal("0")) / len(checks)) if checks else None
        self.model_version = "rules-v1"
        self.predicted_at = timezone.now()
        if save:
            self.save(update_fields=["potability_probability", "model_version", "predicted_at"])
        return self.potability_probability

    def evaluate_rules(self):
        return [rule for rule in AlertRule.objects.filter(active=True) if rule.evaluate(self)]

    def __str__(self):
        return f"Test {self.sampled_at:%Y-%m-%d} · {self.zone}"


class AlertRule(models.Model):
    PARAMETER_CHOICES = [(p, p.replace("_", " ").title()) for p in (
        "ph", "turbidity_ntu", "chlorine_mg_l", "conductivity_us_cm", "potability_probability",
    )]
    OPERATOR_CHOICES = [(value, value) for value in (
        "gt", "gte", "lt", "lte", "eq", "neq", ">", ">=", "<", "<=", "=", "==", "!="
    )]
    SEVERITY_CHOICES = [(value, value.title()) for value in ("info", "warning", "critical")]

    name = models.CharField(max_length=150)
    version_code = models.CharField(max_length=40, default="v1")
    parameter = models.CharField(max_length=40, choices=PARAMETER_CHOICES)
    operator = models.CharField(max_length=4, choices=OPERATOR_CHOICES)
    threshold = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=30, blank=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="warning")
    source_reference = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    def evaluate(self, subject):
        value = getattr(subject, self.parameter, subject)
        if value is None:
            return False
        operations = {
            "gt": operator.gt, ">": operator.gt, "gte": operator.ge, ">=": operator.ge,
            "lt": operator.lt, "<": operator.lt, "lte": operator.le, "<=": operator.le,
            "eq": operator.eq, "=": operator.eq, "==": operator.eq,
            "neq": operator.ne, "!=": operator.ne,
        }
        return operations[self.operator](value, self.threshold)

    def __str__(self):
        return self.name


class LeakIncident(models.Model):
    STATUS_CHOICES = [("investigation", "Investigation"), ("resolved", "Resolved")]

    reference = models.CharField(max_length=40, unique=True, blank=True)
    meter_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    meter_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    meter = GenericForeignKey("meter_content_type", "meter_object_id")
    trigger_reading_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    trigger_reading_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    trigger_reading = GenericForeignKey("trigger_reading_content_type", "trigger_reading_object_id")
    trigger_test = models.ForeignKey(WaterQualityTest, on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    rule = models.ForeignKey(AlertRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    technician = models.ForeignKey("accounts.NetworkTechnician", on_delete=models.SET_NULL, null=True, blank=True, related_name="leak_incidents")
    suspected_pipe = models.ForeignKey("infrastructure.WaterPipe", on_delete=models.SET_NULL, null=True, blank=True, related_name="leak_incidents")
    suspected_pump = models.ForeignKey("infrastructure.WaterPump", on_delete=models.SET_NULL, null=True, blank=True, related_name="leak_incidents")
    position_on_pipe = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal("0.5"), validators=[MinValueValidator(0), MaxValueValidator(1)])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="investigation")
    description = models.TextField(blank=True)
    trigger_evidence = models.JSONField(default=dict, blank=True)
    opened_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(suspected_pipe__isnull=True) | Q(suspected_pump__isnull=True),
                name="leak_incident_one_target_max",
            ),
        ]
        ordering = ["-opened_at"]

    def clean(self):
        super().clean()
        if self.suspected_pipe_id and self.suspected_pump_id:
            raise ValidationError("Un incident ne peut cibler qu'une canalisation ou une pompe.")
        if self.resolved_at and self.status != "resolved":
            raise ValidationError("Un incident avec une date de résolution doit être résolu.")

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"LI-{timezone.now():%Y%m%d%H%M%S}"
        self.full_clean()
        return super().save(*args, **kwargs)

    def assess_incident(self, save=True):
        matches = self.trigger_test.evaluate_rules() if self.trigger_test else []
        if matches and self.rule is None:
            self.rule = matches[0]
        if matches:
            severity_order = {"info": 0, "warning": 1, "critical": 2}
            self.trigger_evidence = {
                "matched_rules": [rule.pk for rule in matches],
                "severity": max((rule.severity for rule in matches), key=lambda value: severity_order[value]),
            }
        if save:
            self.save()
        return bool(matches)

    def resolve(self, save=True):
        self.status = "resolved"
        self.resolved_at = timezone.now()
        if save:
            self.save(update_fields=["status", "resolved_at"])
        return self

    def __str__(self):
        return self.reference or f"Leak incident {self.pk}"
