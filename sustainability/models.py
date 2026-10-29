from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class WaterSavingsTarget(models.Model):
    site = models.ForeignKey("infrastructure.Site", on_delete=models.CASCADE, related_name="savings_targets")
    period_start = models.DateField()
    period_end = models.DateField()
    baseline_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    target_savings_m3 = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    measured_volume_m3 = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.CheckConstraint(condition=models.Q(period_end__gte=models.F("period_start")), name="target_period_valid"),
        ]

    def clean(self):
        if self.period_end < self.period_start:
            raise ValidationError("The target period must end on or after its start.")

    def measure_progress(self):
        if self.target_savings_m3 == 0:
            return Decimal("0")
        savings = max(self.baseline_volume_m3 - self.measured_volume_m3, Decimal("0"))
        return (savings / self.target_savings_m3 * 100).quantize(Decimal("0.01"))


class WaterSavingsProject(models.Model):
    class ProjectType(models.TextChoices):
        REPAIR = "repair", "Leak repair"
        EFFICIENCY = "efficiency", "Efficiency"
        REUSE = "reuse", "Water reuse"
        AWARENESS = "awareness", "Awareness"

    site = models.ForeignKey("infrastructure.Site", on_delete=models.CASCADE, related_name="savings_projects")
    manager = models.ForeignKey("accounts.AuditManager", on_delete=models.PROTECT, related_name="savings_projects")
    origin_incident = models.ForeignKey("quality_leaks.LeakIncident", on_delete=models.SET_NULL, null=True, blank=True, related_name="savings_projects")
    name = models.CharField(max_length=180)
    project_type = models.CharField(max_length=20, choices=ProjectType.choices)
    investment_tnd = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    annual_savings_m3 = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    annual_net_gain_tnd = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    roi_pct = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    profile_cluster = models.PositiveIntegerField(null=True, blank=True)
    model_version = models.CharField(max_length=40, blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)

    def calculate_roi(self, annual_value_tnd=None, save=True):
        if annual_value_tnd is None:
            annual_value_tnd = self.annual_net_gain_tnd
        if self.investment_tnd == 0:
            self.roi_pct = Decimal("0")
        else:
            self.roi_pct = (Decimal(annual_value_tnd) / self.investment_tnd * 100).quantize(Decimal("0.01"))
        if save:
            self.save(update_fields=["roi_pct"])
        return self.roi_pct

    def classify_profile(self, save=True):
        if self.annual_savings_m3 >= 1000:
            self.profile_cluster = 2
        elif self.annual_savings_m3 >= 250:
            self.profile_cluster = 1
        else:
            self.profile_cluster = 0
        self.model_version = "baseline-0.1"
        self.analyzed_at = timezone.now()
        if save:
            self.save(update_fields=["profile_cluster", "model_version", "analyzed_at"])
        return self.profile_cluster


class WaterAuditReport(models.Model):
    site = models.ForeignKey("infrastructure.Site", on_delete=models.CASCADE, related_name="audit_reports")
    manager = models.ForeignKey("accounts.AuditManager", on_delete=models.PROTECT, related_name="audit_reports")
    projects = models.ManyToManyField(WaterSavingsProject, blank=True, related_name="audit_reports")
    title = models.CharField(max_length=180)
    period_start = models.DateField()
    period_end = models.DateField()
    budget_tnd = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0"))])
    summary = models.TextField(blank=True)
    optimization_result = models.JSONField(default=dict, blank=True)
    optimizer_version = models.CharField(max_length=40, blank=True)
    optimized_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if self.period_end < self.period_start:
            raise ValidationError("The report period must end on or after its start.")

    def optimize_portfolio(self, save=True):
        projects = list(self.projects.order_by("pk"))
        remaining = self.budget_tnd
        selected = []
        for project in sorted(projects, key=lambda item: item.roi_pct or Decimal("0"), reverse=True):
            if project.investment_tnd <= remaining:
                selected.append(project)
                remaining -= project.investment_tnd
        self.optimization_result = {
            "selected_project_ids": [project.pk for project in selected],
            "selected_investment_tnd": str(self.budget_tnd - remaining),
            "remaining_budget_tnd": str(remaining),
            "estimated_savings_m3": str(sum((project.annual_savings_m3 for project in selected), Decimal("0"))),
        }
        self.optimizer_version = "greedy-baseline-0.1"
        self.optimized_at = timezone.now()
        if save:
            self.save(update_fields=["optimization_result", "optimizer_version", "optimized_at"])
        return self.optimization_result

    def generate_pdf(self):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ImportError as exc:
            raise ValidationError("Install reportlab to generate audit PDFs.") from exc
        output = BytesIO()
        document = canvas.Canvas(output, pagesize=A4)
        document.setTitle(self.title)
        document.drawString(48, 800, self.title)
        document.drawString(48, 780, f"Site: {self.site}")
        document.drawString(48, 760, f"Period: {self.period_start} to {self.period_end}")
        document.drawString(48, 720, self.summary[:110] if self.summary else "No summary provided.")
        document.save()
        self.generated_at = timezone.now()
        self.save(update_fields=["generated_at"])
        return output.getvalue()
