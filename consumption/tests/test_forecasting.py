from datetime import date, timedelta
from decimal import Decimal
import importlib.util
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from consumption.models import MeterReading
from consumption.services.forecasting import BASELINE_VERSION, train_meter
from .factories import meter, reading

HAS_ML = all(importlib.util.find_spec(name) for name in ("lightgbm", "joblib", "sklearn"))


class ForecastTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(AQUAMIND_CONSUMPTION_MODEL_DIR=directory))
        self.meter = meter()

    def test_sparse_readings_use_actual_elapsed_time(self):
        reading(self.meter, date(2026, 1, 1), 100)
        reading(self.meter, date(2026, 1, 11), 120)
        result = self.meter.forecast_consumption(30)
        self.assertEqual(result["forecast_m3"], "60.000")
        self.assertTrue(result["is_baseline"])
        self.assertEqual(self.meter.model_version, BASELINE_VERSION)
        self.assertIsNotNone(self.meter.predicted_at)
        self.assertEqual(result["tariff_alerts"][0]["status"], "unavailable")

    def test_no_forecast_without_enough_readings(self):
        with self.assertRaises(ValidationError):
            self.meter.forecast_consumption()
        reading(self.meter, date(2026, 1, 1), 100)
        with self.assertRaises(ValidationError):
            self.meter.forecast_consumption()

    def test_horizon_is_bounded_and_not_a_boolean(self):
        for days in (0, 366, True, 1.5, "30"):
            with self.subTest(days=days), self.assertRaises(ValidationError):
                self.meter.forecast_consumption(days)

    def _daily_history(self):
        index = Decimal("100")
        for offset in range(46):
            index += Decimal("2") + Decimal(offset % 7) / 10
            reading(self.meter, date(2026, 1, 1) + timedelta(days=offset), index)

    @skipUnless(HAS_ML, "Optional LightGBM dependencies are not installed")
    def test_real_lightgbm_training_and_prediction(self):
        self._daily_history()
        metrics = train_meter(self.meter)
        self.assertGreater(metrics["samples"], 20)
        self.assertGreaterEqual(metrics["holdout_mae_m3_day"], 0)
        result = self.meter.forecast_consumption(7)
        self.assertFalse(result["is_baseline"])
        self.assertEqual(result["model_version"], metrics["model_version"])
        self.assertGreater(Decimal(result["forecast_m3"]), 0)

    @skipUnless(HAS_ML, "Optional LightGBM dependencies are not installed")
    def test_changed_training_history_requires_retraining(self):
        self._daily_history()
        train_meter(self.meter)
        first = self.meter.readings.first()
        MeterReading.objects.filter(pk=first.pk).update(index_m3=first.index_m3 - 1)
        with self.assertRaisesMessage(ValidationError, "Training readings have changed"):
            self.meter.forecast_consumption(7)

    @skipUnless(HAS_ML, "Optional LightGBM dependencies are not installed")
    def test_sparse_history_is_not_fabricated_into_daily_ml_samples(self):
        for offset in range(40):
            reading(self.meter, date(2026, 1, 1) + timedelta(days=offset * 2), 100 + offset * 4)
        with self.assertRaisesMessage(ValidationError, "consecutive daily"):
            train_meter(self.meter)
