"""
Construit le JSON lu par la maquette 3D (static/infrastructure/maquette.js).

Le format est décrit dans docs/CONTRAT_JSON.md. Toute nouvelle clé doit y être ajoutée.
"""
from django.urls import reverse
from django.utils import timezone

from accounts.models import NetworkTechnician

from ..models import MaintenanceWork, WaterPipe, WaterPump
from .integration import incidents_payload, meters_payload

PLACEHOLDER = "__id__"


def _url_template(name: str) -> str:
    return reverse(name, args=[987654321]).replace("987654321", PLACEHOLDER)


def _f(v):
    return None if v is None else float(v)


def _d(v):
    if v is None:
        return None
    return timezone.localtime(v).date().isoformat() if hasattr(v, "tzinfo") and hasattr(v, "hour") else v.isoformat()


def _equipment_common(eq, today: str) -> dict:
    when = _d(eq.predicted_at) or today
    return {
        "id": eq.pk,
        "type": eq.kind,
        "reference": eq.reference,
        "zone": eq.zone_id,
        "installation_date": _d(eq.installation_date),
        "status": eq.status,
        "failure_risk_30d": _f(eq.failure_risk_30d),
        "model_version": eq.model_version,
        "replacement_cost_tnd": float(eq.estimate_replacement_cost()),
        # Le modèle ne garde que la dernière prédiction : un seul point d'historique.
        "history": [[when, eq.status, _f(eq.failure_risk_30d)]],
    }


def build_payload(site, user=None) -> dict:
    today = timezone.localdate().isoformat()
    zones = list(site.zones.all().order_by("code"))
    pipes = WaterPipe.objects.filter(zone__site=site).order_by("-is_main_supply", "reference")
    pumps = WaterPump.objects.filter(zone__site=site).order_by("reference")
    works = (
        MaintenanceWork.objects.filter(pipe__zone__site=site) | MaintenanceWork.objects.filter(pump__zone__site=site)
    ).select_related("pipe", "pump").distinct().order_by("scheduled_at")

    equipment = []
    for p in pipes:
        e = _equipment_common(p, today)
        e.update({"role": "main" if p.is_main_supply else "branch", "material": p.material,
                  "length_m": _f(p.length_m), "diameter_mm": p.diameter_mm})
        equipment.append(e)
    for p in pumps:
        e = _equipment_common(p, today)
        e.update({"power_kw": _f(p.power_kw), "rated_flow_m3_h": _f(p.rated_flow_m3_h), "efficiency_pct": _f(p.efficiency_pct)})
        equipment.append(e)

    tech_ids = {w.technician_id for w in works}
    technicians = NetworkTechnician.objects.filter(active=True) | NetworkTechnician.objects.filter(pk__in=tech_ids)

    return {
        "site": {"id": site.pk, "code": site.code, "name": site.name, "site_type": site.get_site_type_display(),
                 "governorate": site.governorate, "address": site.address},
        "today": today,
        "can_edit": bool(user and user.is_authenticated and user.has_perm("infrastructure.change_waterzone")),
        "urls": {
            "zone_position": _url_template("infrastructure:zone_position"),
            "pipe_detail": _url_template("infrastructure:pipe_detail"),
            "pump_detail": _url_template("infrastructure:pump_detail"),
            "work_detail": _url_template("infrastructure:work_detail"),
            "work_create": reverse("infrastructure:work_create"),
            "zone_edit": _url_template("infrastructure:zone_update"),
        },
        "technicians": [{"id": t.pk, "name": t.display_identity()} for t in technicians.distinct()],
        "zones": [{
            "id": z.pk, "code": z.code, "name": z.name, "usage": z.usage,
            "service_pressure_bar": _f(z.service_pressure_bar),
            "kind": z.display_kind, "floors": z.floors, "roof": "flat" if z.floors > 1 else "gable",
            "pos_x": _f(z.pos_x), "pos_y": _f(z.pos_y),
        } for z in zones],
        "equipment": equipment,
        "works": [{
            "id": w.pk, "reference": w.reference,
            "pipe": w.pipe.reference if w.pipe_id else None,
            "pump": w.pump.reference if w.pump_id else None,
            "technician": w.technician_id, "maintenance_type": w.maintenance_type,
            "scheduled_at": _d(w.scheduled_at), "completed_at": _d(w.completed_at),
            "cost_tnd": _f(w.cost_tnd), "work_summary": w.work_summary,
        } for w in works],
        "meters": meters_payload(site),       # Student 2
        "incidents": incidents_payload(site),  # Student 3
    }
