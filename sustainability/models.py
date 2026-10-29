from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.urls import reverse


class ConservationTarget(models.Model):
    site = models.ForeignKey("infrastructure.Site", on_delete=models.CASCADE, related_name="conservation_targets")
    name = models.CharField(max_length=150)
    period_start = models.DateField()
    period_end = models.DateField()
    baseline_m3 = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    target_reduction_percent = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    department = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "name"]

    def __str__(self):
        return f"{self.name} ({self.site})"

    @property
    def target_m3(self):
        return (self.baseline_m3 * (Decimal("1") - self.target_reduction_percent / Decimal("100"))).quantize(Decimal("0.001"))

    def get_absolute_url(self):
        return reverse("sustainability:target_detail", args=[self.pk])


class SustainabilityProject(models.Model):
    class ProjectType(models.TextChoices):
        RETROFIT = "retrofit", "Réfection de réseau"
        GREYWATER = "greywater", "Recyclage eaux grises"
        RAINWATER = "rainwater", "Récupération eaux pluviales"
        LOW_FLOW = "low_flow", "Équipements bas débit"
        OTHER = "other", "Autre"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposé"
        APPROVED = "approved", "Approuvé"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED = "completed", "Terminé"
        CANCELLED = "cancelled", "Annulé"

    site = models.ForeignKey("infrastructure.Site", on_delete=models.CASCADE, related_name="sustainability_projects")
    name = models.CharField(max_length=160)
    project_type = models.CharField(max_length=20, choices=ProjectType.choices, default=ProjectType.OTHER)
    description = models.TextField(blank=True)
    budget_tnd = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    expected_savings_m3 = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    expected_annual_savings_tnd = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    start_date = models.DateField(null=True, blank=True)
    completion_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "name"]

    def __str__(self):
        return self.name

    @property
    def payback_months(self):
        if not self.expected_annual_savings_tnd:
            return None
        return (self.budget_tnd / self.expected_annual_savings_tnd * 12).quantize(Decimal("0.1"))

    def get_absolute_url(self):
        return reverse("sustainability:project_detail", args=[self.pk])


class MeasuredBenefit(models.Model):
    project = models.ForeignKey(SustainabilityProject, on_delete=models.CASCADE, related_name="benefits")
    period_start = models.DateField()
    period_end = models.DateField()
    measured_savings_m3 = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    measured_savings_tnd = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    verified = models.BooleanField(default=False)
    evidence = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end"]

    def __str__(self):
        return f"{self.project} · {self.period_start}–{self.period_end}"

    def get_absolute_url(self):
        return reverse("sustainability:benefit_detail", args=[self.pk])


class OptimizationRun(models.Model):
    site = models.ForeignKey("infrastructure.Site", on_delete=models.CASCADE, null=True, blank=True, related_name="optimization_runs")
    budget_tnd = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    objective = models.CharField(max_length=40, default="water_savings")
    solver = models.CharField(max_length=40, default="greedy-fallback")
    recommendations = models.JSONField(default=list)
    total_cost_tnd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    projected_savings_m3 = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    projected_annual_savings_tnd = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payback_months = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Optimisation {self.created_at:%Y-%m-%d %H:%M}"

    def get_absolute_url(self):
        return reverse("sustainability:optimization_detail", args=[self.pk])


class AuditReport(models.Model):
    site = models.ForeignKey("infrastructure.Site", on_delete=models.CASCADE, null=True, blank=True, related_name="audit_reports")
    period_start = models.DateField()
    period_end = models.DateField()
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Audit {self.period_start}–{self.period_end}"
