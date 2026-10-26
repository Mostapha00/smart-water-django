from django.contrib import admin

from .models import MaintenanceWork, Site, WaterPipe, WaterPump, WaterZone


class WaterZoneInline(admin.TabularInline):
    model = WaterZone
    extra = 0
    fields = ("code", "name", "usage", "service_pressure_bar", "display_kind", "floors")


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "site_type", "governorate", "created_at")
    list_filter = ("site_type", "governorate")
    search_fields = ("code", "name", "address")
    inlines = [WaterZoneInline]


@admin.register(WaterZone)
class WaterZoneAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "site", "usage", "service_pressure_bar")
    list_filter = ("site", "display_kind")
    search_fields = ("code", "name", "site__name")


@admin.action(description="Recalculer le risque de panne à 30 jours")
def predict_risk(modeladmin, request, queryset):
    for eq in queryset:
        eq.predict_failure_30d()
    modeladmin.message_user(request, f"{queryset.count()} équipement(s) recalculé(s).")


class EquipmentAdmin(admin.ModelAdmin):
    list_filter = ("status", "zone__site")
    search_fields = ("reference", "zone__name", "zone__site__name")
    readonly_fields = ("failure_risk_30d", "model_version", "predicted_at")
    actions = [predict_risk]


@admin.register(WaterPipe)
class WaterPipeAdmin(EquipmentAdmin):
    list_display = ("reference", "zone", "material", "length_m", "diameter_mm", "status", "failure_risk_30d")


@admin.register(WaterPump)
class WaterPumpAdmin(EquipmentAdmin):
    list_display = ("reference", "zone", "power_kw", "rated_flow_m3_h", "efficiency_pct", "status", "failure_risk_30d")


@admin.register(MaintenanceWork)
class MaintenanceWorkAdmin(admin.ModelAdmin):
    list_display = ("reference", "target", "technician", "maintenance_type", "scheduled_at", "completed_at", "cost_tnd")
    list_filter = ("maintenance_type", "technician")
    date_hierarchy = "scheduled_at"
