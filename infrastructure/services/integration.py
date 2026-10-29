"""
Lecture des données des autres modules, sans dépendance forte.

Les modèles optionnels sont resolved dynamically so the infrastructure module keeps
working during migrations and in installations that do not enable every feature.

Les noms de champs attendus sont ceux du diagramme de classes (voir docs/CONTRAT_JSON.md).
"""
from datetime import datetime

from django.apps import apps
from django.utils import timezone


def _model(app_label: str, name: str):
    try:
        return apps.get_model(app_label, name)
    except LookupError:
        return None


def meters_for_zone(zone):
    """Liste des compteurs de la zone, ou None si le module consumption n'existe pas encore."""
    WaterMeter = _model("consumption", "WaterMeter")
    if WaterMeter is None:
        return None
    return list(WaterMeter.objects.filter(zone=zone))


def meters_payload(site) -> list[dict]:
    WaterMeter = _model("consumption", "WaterMeter")
    MeterReading = _model("consumption", "MeterReading")
    if WaterMeter is None or MeterReading is None:
        return []
    out = []
    for m in WaterMeter.objects.filter(zone__site=site).order_by("serial_number"):
        readings = MeterReading.objects.filter(meter=m).order_by("recorded_at").values_list("recorded_at", "index_m3")
        out.append({
            "serial_number": m.serial_number,
            "zone": m.zone_id,
            "customer_category": getattr(m, "customer_category", ""),
            "forecast_m3": _num(getattr(m, "forecast_m3", None)),
            "horizon_days": getattr(m, "horizon_days", None),
            "readings": [[_date(d), _num(i)] for d, i in readings],
        })
    return out


def incidents_payload(site) -> list[dict]:
    LeakIncident = _model("quality_leaks", "LeakIncident")
    if LeakIncident is None:
        return []
    qs = LeakIncident.objects.filter(suspected_pipe__zone__site=site) | LeakIncident.objects.filter(suspected_pump__zone__site=site)
    out = []
    for inc in qs.distinct():
        meter = getattr(inc, "meter", None)
        rule = getattr(inc, "rule", None)
        out.append({
            "reference": getattr(inc, "reference", None) or f"LI-{inc.pk:04d}",
            "meter": getattr(meter, "serial_number", None),
            "suspected_pipe": getattr(getattr(inc, "suspected_pipe", None), "reference", None),
            "suspected_pump": getattr(getattr(inc, "suspected_pump", None), "reference", None),
            "position_on_pipe": _num(getattr(inc, "position_on_pipe", None)) or 0.5,
            "technician": getattr(inc, "technician_id", None),
            "rule": str(rule) if rule else "",
            "status": "resolved" if getattr(inc, "resolved_at", None) else "investigation",
            "description": getattr(inc, "description", ""),
            "trigger_reading": None,
            "opened_at": _date(getattr(inc, "opened_at", None)),
            "resolved_at": _date(getattr(inc, "resolved_at", None)),
        })
    return out


def _num(v):
    return None if v is None else float(v)


def _date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return (timezone.localtime(v) if timezone.is_aware(v) else v).date().isoformat()
    return v.isoformat()
