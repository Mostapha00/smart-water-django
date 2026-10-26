from django.contrib import admin

from .models import AuditManager, NetworkTechnician


@admin.register(NetworkTechnician)
class NetworkTechnicianAdmin(admin.ModelAdmin):
    list_display = ("display_identity", "staff_id", "specialty", "email", "active")
    list_filter = ("active", "specialty")
    search_fields = ("name", "first_name", "staff_id", "email")


@admin.register(AuditManager)
class AuditManagerAdmin(admin.ModelAdmin):
    list_display = ("display_identity", "staff_id", "organization", "email", "active")
    list_filter = ("active",)
    search_fields = ("name", "first_name", "staff_id", "email")
