from django.contrib import admin  # noqa: F401

# Student 4 : enregistrer ici les modèles du module dans l'admin.
from django.contrib import admin

from .models import WaterAuditReport, WaterSavingsProject, WaterSavingsTarget


@admin.register(WaterSavingsTarget)
class WaterSavingsTargetAdmin(admin.ModelAdmin):
    list_display = ("site", "period_start", "period_end", "target_savings_m3", "measure_progress")
    list_filter = ("site",)


@admin.register(WaterSavingsProject)
class WaterSavingsProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "site", "project_type", "investment_tnd", "roi_pct", "profile_cluster")
    list_filter = ("project_type", "site")


@admin.register(WaterAuditReport)
class WaterAuditReportAdmin(admin.ModelAdmin):
    list_display = ("title", "site", "manager", "period_start", "period_end", "budget_tnd")
    list_filter = ("site", "period_start")
