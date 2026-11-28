from datetime import datetime, time

from django.db.models import Q, Sum
from django.utils import timezone

from consumption.models import WaterMeter
from infrastructure.models import Site, WaterPipe, WaterPump
from quality_leaks.models import LeakIncident, WaterQualityTest


def incidents_for(sites):
    """Incidents rattachés aux sites : par l'équipement suspecté, l'analyse ou le compteur."""
    meter_ids = list(WaterMeter.objects.filter(zone__site__in=sites).values_list("pk", flat=True))
    return LeakIncident.objects.filter(
        Q(suspected_pipe__zone__site__in=sites) | Q(suspected_pump__zone__site__in=sites)
        | Q(trigger_test__zone__site__in=sites)
        | Q(meter_content_type__app_label="consumption", meter_content_type__model="watermeter", meter_object_id__in=meter_ids)
    ).distinct()


def executive_metrics(site=None, start=None, end=None):
    """Indicateurs du tableau de bord et du rapport d'audit.

    Avec start/end (dates), la consommation est celle de la période, d'après les relevés réels ;
    sans période, c'est la consommation totale enregistrée.
    """
    sites = Site.objects.filter(pk=site.pk) if site else Site.objects.all()
    tz = timezone.get_current_timezone()
    lower = datetime.combine(start, time.min, tz) if start else None
    upper = datetime.combine(end, time.max, tz) if end else timezone.now()
    consumption = 0
    for meter in WaterMeter.objects.filter(zone__site__in=sites):
        first = meter.readings.order_by("recorded_at").first()
        result = meter.volume_between(lower or (first.recorded_at if first else upper), upper)
        if result:
            consumption += result[0]
    tests = WaterQualityTest.objects.filter(zone__site__in=sites).exclude(potability_probability__isnull=True)
    if start:
        tests = tests.filter(sampled_at__gte=lower, sampled_at__lte=upper)
    quality = tests.aggregate(value=Sum("potability_probability"))["value"]
    quality_score = (quality / tests.count()) if quality is not None else None
    return {
        "sites": sites.count(),
        "consumption_m3": float(consumption),
        "active_leaks": incidents_for(sites).filter(status="investigation").count(),
        "quality_score": float(quality_score) if quality_score is not None else None,
        "equipment": WaterPipe.objects.filter(zone__site__in=sites).count() + WaterPump.objects.filter(zone__site__in=sites).count(),
        "projects": sum(s.sustainability_projects.count() for s in sites),
    }
