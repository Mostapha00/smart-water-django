from django.contrib import admin
from .models import AuditReport, ConservationTarget, MeasuredBenefit, OptimizationRun, SustainabilityProject

admin.site.register([ConservationTarget, SustainabilityProject, MeasuredBenefit, OptimizationRun, AuditReport])
