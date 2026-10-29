from django.db.models import Sum
from consumption.models import MeterReading
from quality_leaks.models import LeakIncident, WaterQualityTest
from infrastructure.models import Site, WaterPipe, WaterPump
from .optimization import optimize_projects


def executive_metrics(site=None):
    sites = Site.objects.filter(pk=site.pk) if site else Site.objects.all()
    meters = MeterReading.objects.filter(meter__zone__site__in=sites)
    readings = list(meters.order_by("meter_id", "recorded_at"))
    consumption = sum((r.calculate_volume() or 0 for r in readings), 0)
    tests = WaterQualityTest.objects.filter(zone__site__in=sites)
    quality = tests.exclude(potability_probability__isnull=True).aggregate(value=Sum("potability_probability"))["value"]
    quality_score = (quality / tests.exclude(potability_probability__isnull=True).count()) if quality is not None else None
    return {
        "sites": sites.count(),
        "consumption_m3": float(consumption),
        "active_leaks": LeakIncident.objects.filter(status="investigation").count(),
        "quality_score": float(quality_score) if quality_score is not None else None,
        "equipment": WaterPipe.objects.filter(zone__site__in=sites).count() + WaterPump.objects.filter(zone__site__in=sites).count(),
        "projects": sum(s.sustainability_projects.count() for s in sites),
    }
