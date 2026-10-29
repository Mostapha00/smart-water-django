from django.contrib import admin

from .models import AlertRule, LeakIncident, WaterQualityTest


@admin.register(WaterQualityTest)
class WaterQualityTestAdmin(admin.ModelAdmin):
    list_display = ("zone", "sampled_at", "laboratory", "potability_probability")
    list_filter = ("laboratory", "sampled_at")


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "parameter", "operator", "threshold", "severity", "active")
    list_filter = ("active", "severity", "parameter")


@admin.register(LeakIncident)
class LeakIncidentAdmin(admin.ModelAdmin):
    list_display = ("reference", "status", "suspected_pipe", "suspected_pump", "opened_at", "resolved_at")
    list_filter = ("status", "opened_at")
    search_fields = ("reference", "description")
