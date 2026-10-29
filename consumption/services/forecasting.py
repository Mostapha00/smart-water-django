"""A labelled baseline plus an optional, locally trained LightGBM model."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from consumption.models import TariffBand, WaterMeter
from .billing import quote_service

FEATURES = ["weekday", "month", "lag_1", "mean_7"]
BASELINE_VERSION = "mean-daily-rate-baseline-1"


def model_path(meter):
    directory = Path(getattr(settings, "AQUAMIND_CONSUMPTION_MODEL_DIR", Path(settings.MEDIA_ROOT) / "consumption_models"))
    return directory / f"meter-{meter.pk}.joblib"


def signature(rows):
    values = [(r.recorded_at.isoformat(), str(r.index_m3)) for r in rows]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def daily_series(rows):
    """Daily ML needs real daily intervals; sparse monthly indexes are not daily data."""
    rates, days = [], []
    for before, after in zip(rows, rows[1:]):
        seconds = (after.recorded_at - before.recorded_at).total_seconds()
        if not 86100 <= seconds <= 86700:
            raise ValidationError("LightGBM requires consecutive daily readings, approximately 24 hours apart.")
        rates.append(float(after.index_m3 - before.index_m3))
        days.append(timezone.localdate(after.recorded_at))
    return rates, days


def features(day, history):
    return [day.weekday(), day.month, history[-1], sum(history[-7:]) / len(history[-7:])]


def train_meter(meter):
    """Train outside HTTP requests, report a chronological holdout, save an artifact."""
    try:
        from lightgbm import LGBMRegressor
        import joblib
    except ImportError as exc:
        raise ValidationError("Install requirements-ml.txt to train a LightGBM forecast.") from exc
    rows = list(meter.readings.order_by("recorded_at"))
    if len(rows) < 40:
        raise ValidationError("Training requires at least 40 consecutive daily readings.")
    rates, days = daily_series(rows)
    x = [features(days[i], rates[:i]) for i in range(7, len(rates))]
    y = rates[7:]
    split = max(1, int(len(x) * 0.8))
    options = dict(n_estimators=80, num_leaves=7, min_child_samples=3, random_state=42, n_jobs=1, verbosity=-1)
    validation_model = LGBMRegressor(**options).fit(x[:split], y[:split])
    predictions = validation_model.predict(x[split:])
    mae = sum(abs(float(a) - b) for a, b in zip(predictions, y[split:])) / len(predictions)
    model = LGBMRegressor(**options).fit(x, y)
    version = "lightgbm-" + timezone.now().strftime("%Y%m%dT%H%M%S%f")
    artifact = {"schema": 1, "features": FEATURES, "model": model, "version": version,
                "training_start": rows[0].recorded_at, "training_end": rows[-1].recorded_at,
                "signature": signature(rows), "samples": len(x), "holdout_mae_m3_day": mae}
    path = model_path(meter)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".joblib.tmp")
    joblib.dump(artifact, temporary)
    temporary.replace(path)
    return {"path": str(path), "model_version": version, "samples": len(x), "holdout_mae_m3_day": mae}


@transaction.atomic
def forecast_meter(meter, horizon_days=30):
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or not 1 <= horizon_days <= 365:
        raise ValidationError("horizon_days must be an integer between 1 and 365.")
    locked = WaterMeter.objects.select_for_update().get(pk=meter.pk)
    rows = list(locked.readings.order_by("recorded_at"))
    if len(rows) < 2:
        raise ValidationError("At least two readings are required for a consumption forecast.")
    last = rows[-1]
    # A baseline can use sparse indexes because it uses the actual elapsed time.
    recent = rows[-91:]
    elapsed = Decimal(str((recent[-1].recorded_at - recent[0].recorded_at).total_seconds())) / Decimal("86400")
    mean = (recent[-1].index_m3 - recent[0].index_m3) / elapsed
    forecast = mean * horizon_days
    version = BASELINE_VERSION
    path = model_path(locked)
    if path.exists():
        try:
            import joblib
        except ImportError as exc:
            raise ValidationError("The trained forecast requires requirements-ml.txt.") from exc
        # Only operator-created server artifacts are loaded, never user uploads.
        artifact = joblib.load(path)
        if artifact.get("schema") != 1 or artifact.get("features") != FEATURES:
            raise ValidationError("Unsupported forecast artifact. Retrain this meter.")
        training_rows = [r for r in rows if artifact["training_start"] <= r.recorded_at <= artifact["training_end"]]
        if signature(training_rows) != artifact["signature"]:
            raise ValidationError("Training readings have changed. Retrain this meter before forecasting.")
        rates, _ = daily_series(rows)
        total = 0.0
        for offset in range(1, horizon_days + 1):
            day = timezone.localdate(last.recorded_at) + timedelta(days=offset)
            value = float(artifact["model"].predict([features(day, rates)])[0])
            if not math.isfinite(value):
                raise ValidationError("The trained model returned an invalid forecast.")
            value = max(0.0, value)
            rates.append(value)
            total += value
        forecast, version = Decimal(str(total)), artifact["version"]
    locked.forecast_m3 = forecast.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    locked.horizon_days, locked.model_version, locked.predicted_at = horizon_days, version, timezone.now()
    locked.save(update_fields=["forecast_m3", "horizon_days", "model_version", "predicted_at"])
    meter.refresh_from_db()
    start = timezone.localdate(last.recorded_at)
    end = start + timedelta(days=horizon_days)
    alerts = []
    for service in TariffBand.Service.values:
        try:
            band, amount, _ = quote_service(service, meter.customer_category, start, end, meter.forecast_m3)
            alerts.append({"service": service, "status": "available", "band_id": band.pk,
                           "above_first_band": band.lower_bound_m3 > 0, "estimated_charge_tnd": str(amount)})
        except ValidationError as exc:
            alerts.append({"service": service, "status": "unavailable", "message": " ".join(exc.messages)})
    return {"forecast_m3": str(meter.forecast_m3), "horizon_days": horizon_days,
            "model_version": version, "is_baseline": version == BASELINE_VERSION,
            "predicted_at": meter.predicted_at.isoformat(), "starts_at": last.recorded_at.isoformat(),
            "tariff_alerts": alerts}
