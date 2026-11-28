"""
Détection de consommations anormales (fuites possibles) sur les relevés de compteurs.

Isolation Forest (non supervisé : aucun exemple de fuite n'est nécessaire), ajusté sur les intervalles
entre relevés de TOUS les compteurs. Chaque intervalle est décrit par rapport au niveau habituel de
son compteur, pour comparer une usine et une école :
- log_ratio_median : consommation journalière / médiane du compteur (en log) ;
- log_change       : consommation journalière / celle de l'intervalle précédent (en log).
(La durée de l'intervalle n'est volontairement PAS une variable : un mois de février plus court
n'est pas une fuite.)

Un relevé est signalé (is_anomaly) s'il est atypique pour le modèle ET au moins LEAK_MIN_RATIO fois
la médiane du compteur : une fuite augmente nettement la consommation, une baisse n'en est pas une.
anomaly_score > 0 = atypique (plus il est grand, plus c'est inhabituel). Ce n'est PAS une probabilité.

Sans scikit-learn ou avec moins de MIN_SAMPLES intervalles : règle simple « rolling-ratio-1 »
(consommation > 1,4 × moyenne des intervalles précédents).

Si le DERNIER relevé d'un compteur est signalé, un incident de fuite est ouvert automatiquement
(quality_leaks/services.py), sans doublon tant qu'un incident est en investigation.
"""
from __future__ import annotations

import math
from decimal import Decimal
from statistics import median

from django.utils import timezone

MODEL_VERSION = "isolation-forest-1"
RULE_VERSION = "rolling-ratio-1"
MIN_SAMPLES = 20
MAX_SAMPLES = 20000
LEAK_MIN_RATIO = 1.3  # au moins +30 % par rapport à l'habitude du compteur
EPS = 1e-6


def _intervals(readings):
    """[(reading, rate_per_day, days)] pour chaque relevé qui a un relevé précédent."""
    out = []
    for prev, cur in zip(readings, readings[1:]):
        days = (cur.recorded_at - prev.recorded_at).total_seconds() / 86400
        volume = float(cur.index_m3 - prev.index_m3)
        if days > 0 and volume >= 0:
            out.append((cur, volume / days, days))
    return out


def _features(intervals):
    rates = [rate for _, rate, _ in intervals]
    mid = median(rates) if rates else 0.0
    rows = []
    for i, (_, rate, _days) in enumerate(intervals):
        prev = rates[i - 1] if i else rate
        rows.append([math.log((rate + EPS) / (mid + EPS)), math.log((rate + EPS) / (prev + EPS))])
    return rows, mid


def analyze(meters=None) -> dict:
    """Analyse les relevés et enregistre score, drapeau, version et date. Renvoie un résumé."""
    from consumption.models import MeterReading, WaterMeter

    all_meters = list(WaterMeter.objects.prefetch_related("readings"))
    targets = {m.pk for m in meters} if meters is not None else {m.pk for m in all_meters}
    per_meter = {m.pk: _intervals(sorted(m.readings.all(), key=lambda r: (r.recorded_at, r.pk))) for m in all_meters}
    total = sum(len(v) for v in per_meter.values())
    now = timezone.now()

    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        IsolationForest = None

    changed = []
    if IsolationForest is not None and total >= MIN_SAMPLES:
        X, owners = [], []
        for meter_id, intervals in per_meter.items():
            rows, mid = _features(intervals)
            X.extend(rows)
            owners.extend((meter_id, reading, rate, mid) for (reading, rate, _), _row in zip(intervals, rows))
        X, owners = X[-MAX_SAMPLES:], owners[-MAX_SAMPLES:]
        model = IsolationForest(n_estimators=200, contamination="auto", random_state=42).fit(X)
        scores = model.decision_function(X)  # < 0 = atypique
        for (meter_id, reading, rate, mid), score in zip(owners, scores):
            if meter_id not in targets:
                continue
            reading.anomaly_score = Decimal(str(round(-float(score), 3)))
            reading.is_anomaly = bool(score < 0 and rate >= LEAK_MIN_RATIO * mid)
            reading.model_version, reading.analyzed_at = MODEL_VERSION, now
            changed.append(reading)
        version = MODEL_VERSION
    else:
        for meter_id in targets:
            for reading, _rate, _days in per_meter.get(meter_id, []):
                rule_flag(reading, save=False, now=now)
                changed.append(reading)
        version = RULE_VERSION

    MeterReading.objects.bulk_update(changed, ["anomaly_score", "is_anomaly", "model_version", "analyzed_at"], batch_size=500)
    opened = _open_incidents({meter_id: per_meter[meter_id] for meter_id in targets if per_meter.get(meter_id)})
    return {"version": version, "analyzed": len(changed), "anomalies": sum(1 for r in changed if r.is_anomaly),
            "incidents_opened": opened}


def _open_incidents(per_meter) -> int:
    """Ouvre un incident quand le DERNIER relevé d'un compteur est signalé.

    Les anciens relevés signalés restent visibles sur la fiche du compteur, mais n'ouvrent pas
    d'incident aujourd'hui : seule la situation actuelle demande une intervention.
    """
    from quality_leaks.services import open_leak_incident

    opened = 0
    for intervals in per_meter.values():
        reading, rate, _days = intervals[-1]
        if reading.is_anomaly:
            usual = median(r for _, r, _ in intervals)
            opened += open_leak_incident(reading, rate, usual) is not None
    return opened


def rule_flag(reading, window=3, threshold=Decimal("1.4"), save=True, now=None) -> bool:
    """Règle simple : consommation de l'intervalle > threshold × moyenne des `window` précédents."""
    volume = reading.calculate_volume()
    if volume is None:
        return False
    previous = list(reading.meter.readings.filter(recorded_at__lt=reading.recorded_at).order_by("-recorded_at")[:window + 1])
    volumes = [v for v in (r.calculate_volume() for r in previous) if v is not None and v >= 0]
    average = sum(volumes, Decimal("0")) / len(volumes) if volumes else Decimal("0")
    score = (volume / average) if average else Decimal("0")
    reading.anomaly_score = score.quantize(Decimal("0.001"))
    reading.is_anomaly = bool(average and score > Decimal(str(threshold)))
    reading.model_version, reading.analyzed_at = RULE_VERSION, now or timezone.now()
    if save and reading.pk:
        reading.save(update_fields=["anomaly_score", "is_anomaly", "model_version", "analyzed_at"])
    return reading.is_anomaly
