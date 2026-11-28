"""
Ouverture automatique des incidents (étape 2 du scénario du dossier : « la consommation augmente,
un incident est ouvert »).

- open_leak_incident()    : un relevé signalé par la détection de fuites (consumption/services/anomaly.py).
- open_quality_incident() : une analyse d'eau qui enfreint une règle d'alerte CRITIQUE.

Jamais de doublon : si un incident est déjà en investigation pour le même compteur (ou la même analyse),
rien n'est créé. Les valeurs qui ont déclenché l'incident sont copiées dans trigger_evidence, pour
garder la preuve même si la source change ensuite. Un technicien complète ensuite l'incident
(équipement suspecté, technicien assigné) puis le résout.
"""
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import LeakIncident

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def open_incidents_for(meter):
    ct = ContentType.objects.get_for_model(meter)
    return LeakIncident.objects.filter(meter_content_type=ct, meter_object_id=meter.pk, status="investigation")


@transaction.atomic
def open_leak_incident(reading, rate_m3_day, usual_m3_day):
    """Ouvre un incident pour un relevé de consommation anormale, sauf s'il en existe déjà un ouvert."""
    meter = reading.meter
    if open_incidents_for(meter).exists():
        return None
    incident = LeakIncident(
        meter=meter,
        trigger_reading=reading,
        description=(
            f"Fuite possible détectée automatiquement sur le compteur {meter.serial_number} "
            f"({meter.zone}) : {rate_m3_day:.2f} m³/jour au relevé du {reading.recorded_at:%d/%m/%Y}, "
            f"pour {usual_m3_day:.2f} m³/jour habituellement. À vérifier sur place."
        ),
        trigger_evidence={
            "source": "detection_fuites",
            "reading_id": reading.pk,
            "recorded_at": reading.recorded_at.isoformat(),
            "index_m3": str(reading.index_m3),
            "rate_m3_per_day": round(rate_m3_day, 3),
            "usual_m3_per_day": round(usual_m3_day, 3),
            "anomaly_score": str(reading.anomaly_score),
            "model_version": reading.model_version,
        },
    )
    incident.save()
    return incident


@transaction.atomic
def open_quality_incident(test, matched_rules):
    """Ouvre un incident si l'analyse enfreint au moins une règle critique (sinon, simple avertissement)."""
    critical = [rule for rule in matched_rules if rule.severity == "critical"]
    if not critical or LeakIncident.objects.filter(trigger_test=test, status="investigation").exists():
        return None
    rule = critical[0]
    incident = LeakIncident(
        trigger_test=test,
        rule=rule,
        description=(
            f"Analyse d'eau non conforme ({test.zone}, {test.sampled_at:%d/%m/%Y}) : "
            + ", ".join(f"{r.name} ({r.parameter} {r.operator} {r.threshold})" for r in critical)
            + ". Confirmation par le laboratoire nécessaire."
        ),
        trigger_evidence={
            "source": "analyse_qualite",
            "test_id": test.pk,
            "measurements": {p: (str(getattr(test, p)) if getattr(test, p) is not None else None)
                             for p in ("ph", "turbidity_ntu", "chlorine_mg_l", "conductivity_us_cm", "potability_probability")},
            "matched_rules": [{"id": r.pk, "name": r.name, "version": r.version_code, "severity": r.severity} for r in matched_rules],
            "severity": max((r.severity for r in matched_rules), key=lambda s: SEVERITY_ORDER.get(s, 0)),
        },
    )
    incident.save()
    return incident
