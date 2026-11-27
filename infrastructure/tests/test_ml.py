"""
Tests des modèles d'IA et des solveurs, sur des données construites où la bonne réponse est connue.

Le lanceur de tests (config/test_runner.py) fournit un dossier de modèles vide : chaque test entraîne
ce dont il a besoin. Les tests ML sont ignorés si requirements-ml.txt n'est pas installé.
"""
import importlib.util
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock, skipUnless

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from consumption.models import MeterReading, WaterMeter
from consumption.services import anomaly, forecasting
from infrastructure.models import MaintenanceWork
from infrastructure.services import risk
from infrastructure.services.artifacts import artifact_path, is_ml_version
from infrastructure.services.risk_training import build_dataset, train_failure_model
from sustainability.models import AuditReport, SustainabilityProject
from sustainability.services.optimization import optimize_projects
from sustainability.services.pdf import PdfUnavailable

from .factories import make_pipe, make_pump, make_site, make_tech, make_zone

HAS_SKLEARN = bool(importlib.util.find_spec("sklearn"))
HAS_LIGHTGBM = bool(importlib.util.find_spec("lightgbm"))


class MLTestCase(TestCase):
    """Chaque test a son propre dossier de modèles : un modèle entraîné ici ne fuit pas vers un autre test."""

    def setUp(self):
        super().setUp()
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="aquamind-ml-test-"))
        self.enterContext(override_settings(AQUAMIND_ML_DIR=directory, AQUAMIND_FAILURE_MODEL_PATH=""))


def aware(d):
    return timezone.make_aware(datetime(d.year, d.month, d.day))


def month_starts(start, count):
    out, d = [], start
    for _ in range(count):
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def make_history(meter, rate_for_month, start=date(2023, 3, 1), months=30):
    """Relevés mensuels cumulés ; rate_for_month(i, end_month) = consommation journalière de l'intervalle i."""
    dates = month_starts(start, months + 1)
    index = Decimal("1000")
    MeterReading.objects.create(meter=meter, recorded_at=aware(dates[0]), index_m3=index)
    for i, (a, b) in enumerate(zip(dates, dates[1:])):
        index += Decimal(str(round(rate_for_month(i, b.month) * (b - a).days, 3)))
        MeterReading.objects.create(meter=meter, recorded_at=aware(b), index_m3=index)


class ArtifactLabelTests(TestCase):
    def test_versions_are_classified(self):
        for version in ("random-forest-20261127-0948", "lightgbm-20261127-0948", "isolation-forest-1", "PuLP"):
            self.assertTrue(is_ml_version(version), version)
        for version in ("baseline-0.1", "average-daily-1", "rolling-ratio-1", "rules-v1", "greedy-fallback", "", None):
            self.assertFalse(is_ml_version(version), version)

    def test_badge(self):
        render = lambda v: Template("{% load aquamind_ml %}{% ml_badge v %}").render(Context({"v": v}))  # noqa: E731
        self.assertIn("Modèle IA", render("PuLP"))
        self.assertIn("Règle", render("average-daily-1"))
        self.assertIn("non calculé", render(""))


class FailureRiskTests(MLTestCase):
    def setUp(self):
        super().setUp()
        self.zone = make_zone(make_site())
        self.tech = make_tech()
        now = timezone.now()
        # Trois vieilles canalisations avec des pannes répétées, trois récentes sans panne.
        self.old = [make_pipe(self.zone, reference=f"OLD-{i}", installation_date=date(1990, 1, 1)) for i in range(3)]
        self.new = [make_pipe(self.zone, reference=f"NEW-{i}", installation_date=date(2022, 1, 1)) for i in range(3)]
        for pipe in self.old:
            for days_ago in (60, 200, 400, 600):
                MaintenanceWork.objects.create(technician=self.tech, pipe=pipe, maintenance_type="corrective",
                                               scheduled_at=now - timedelta(days=days_ago))

    def test_features_never_look_into_the_future(self):
        pipe = self.old[0]
        as_of = timezone.now() - timedelta(days=300)
        f = risk.features(pipe, as_of=as_of)
        self.assertEqual(f["interventions_2y"], 2)  # pannes à J-400 et J-600 seulement
        self.assertGreater(f["days_since_last"], 90)

    def test_dataset_labels_failures_in_the_next_30_days(self):
        X, y = build_dataset()
        self.assertGreater(sum(y), 0)
        self.assertGreater(len(y) - sum(y), sum(y))

    @skipUnless(HAS_SKLEARN, "scikit-learn n'est pas installé")
    def test_random_forest_is_trained_used_and_marked_demo(self):
        result = train_failure_model()
        self.assertTrue(result["demo"])
        self.assertTrue(artifact_path(risk.ARTIFACT).exists())
        old_risk = self.old[0].predict_failure_30d()
        new_risk = self.new[0].predict_failure_30d()
        self.assertTrue(self.old[0].model_version.startswith("random-forest-"))
        self.assertGreater(old_risk, new_risk)
        html = Template("{% load aquamind_ml %}{% ml_badge v %}").render(Context({"v": self.old[0].model_version}))
        self.assertIn("démo", html)

    def test_without_history_training_is_refused_and_rule_is_used(self):
        MaintenanceWork.objects.all().delete()
        with self.assertRaises(ValidationError):
            train_failure_model()
        pump = make_pump(self.zone)
        pump.predict_failure_30d()
        self.assertEqual(pump.model_version, risk.BASELINE_VERSION)


class AnomalyTests(MLTestCase):
    def setUp(self):
        super().setUp()
        zone = make_zone(make_site())
        self.meters = [WaterMeter.objects.create(zone=zone, serial_number=f"M-{i}") for i in range(3)]

    def steady(self, base, spike_at=None, drop_at=None):
        def rate(i, _month):
            value = base * (1 + 0.03 * ((i % 3) - 1))
            if i == spike_at:
                value *= 2.5
            if i == drop_at:
                value *= 0.3
            return value
        return rate

    @skipUnless(HAS_SKLEARN, "scikit-learn n'est pas installé")
    def test_isolation_forest_flags_a_spike_but_not_a_drop(self):
        make_history(self.meters[0], self.steady(5, spike_at=9), months=12)
        make_history(self.meters[1], self.steady(40, drop_at=5), months=12)
        make_history(self.meters[2], self.steady(1), months=12)
        result = anomaly.analyze()
        self.assertEqual(result["version"], anomaly.MODEL_VERSION)
        readings = {m.pk: list(m.readings.order_by("recorded_at")) for m in self.meters}
        self.assertTrue(readings[self.meters[0].pk][10].is_anomaly)   # intervalle 9 = relevé 10
        self.assertFalse(readings[self.meters[1].pk][6].is_anomaly)   # une baisse n'est pas une fuite
        self.assertEqual(result["anomalies"], 1)
        self.assertIsNone(readings[self.meters[0].pk][0].is_anomaly)  # premier relevé : rien à comparer

    def test_too_little_data_uses_the_rule(self):
        make_history(self.meters[0], self.steady(5, spike_at=3), months=4)
        self.assertEqual(anomaly.analyze()["version"], anomaly.RULE_VERSION)
        self.assertTrue(self.meters[0].readings.order_by("recorded_at")[4].is_anomaly)

    @skipUnless(HAS_SKLEARN, "scikit-learn n'est pas installé")
    def test_csv_import_view_runs_detection(self):
        for meter in self.meters[1:]:
            make_history(meter, self.steady(10), months=12)
        user = User.objects.create_superuser("admin", "a@example.tn", "x-Pass-12345")
        self.client.force_login(user)
        lines = ["recorded_at,index_m3"]
        index = 0
        for i, d in enumerate(month_starts(date(2025, 1, 1), 13)):
            lines.append(f"{d.isoformat()}T00:00:00+01:00,{index}")
            index += 300 if i != 10 else 900
        csv = StringIO("\n".join(lines))
        csv.name = "r.csv"
        response = self.client.post(reverse("consumption:meter_import", args=[self.meters[0].pk]), {"file": csv}, follow=True)
        self.assertContains(response, "fuite possible")
        self.assertTrue(self.meters[0].readings.filter(is_anomaly=True).exists())


@skipUnless(HAS_LIGHTGBM, "LightGBM n'est pas installé")
class ForecastTests(MLTestCase):
    def setUp(self):
        super().setUp()
        zone = make_zone(make_site())
        # Forte saisonnalité : août et septembre à 30 % du niveau habituel.
        for i, (base, category) in enumerate(((1, "public"), (5, "household"), (20, "commercial"), (60, "industrial"))):
            meter = WaterMeter.objects.create(zone=zone, serial_number=f"F-{i}", customer_category=category)
            make_history(meter, lambda j, month, b=base: b * (0.3 if month in (8, 9) else 1.0) * (1 + 0.02 * ((j % 4) - 1.5)))

    def test_lightgbm_beats_the_average_and_is_used(self):
        result = forecasting.train_consumption_model()
        self.assertLess(result["mae_m3_per_day"], result["baseline_mae_m3_per_day"])
        meter = WaterMeter.objects.get(serial_number="F-3")
        self.assertIsNotNone(meter.forecast_consumption(30))
        self.assertTrue(meter.model_version.startswith("lightgbm-"))

    def test_a_model_worse_than_the_rule_is_not_activated(self):
        forecasting.train_consumption_model()
        self.assertTrue(artifact_path(forecasting.ARTIFACT).exists())

        class Terrible:
            def __init__(self, **kw):
                pass

            def fit(self, X, y):
                return self

            def predict(self, X):
                return [25.0] * len(X)

        with mock.patch("lightgbm.LGBMRegressor", Terrible), self.assertRaises(ValidationError):
            forecasting.train_consumption_model()
        self.assertFalse(artifact_path(forecasting.ARTIFACT).exists())  # l'ancien modèle est retiré aussi
        meter = WaterMeter.objects.get(serial_number="F-0")
        meter.forecast_consumption(30)
        self.assertEqual(meter.model_version, "average-daily-1")


class OptimizationAndPdfTests(MLTestCase):
    def setUp(self):
        super().setUp()
        self.site = make_site()

    def test_pulp_finds_the_optimum_where_greedy_does_not(self):
        # Budget 100 : le tri glouton prend A (meilleur ratio) puis plus rien ne rentre -> 60 m³.
        # L'optimum est B + C -> 90 m³.
        for name, cost, saving in (("A", 60, 61), ("B", 50, 45), ("C", 50, 45)):
            SustainabilityProject.objects.create(site=self.site, name=name, budget_tnd=cost, expected_savings_m3=saving)
        result = optimize_projects(SustainabilityProject.objects.all(), 100)
        self.assertEqual(result["solver"], "PuLP")
        self.assertEqual(sorted(p.name for p in result["projects"]), ["B", "C"])
        self.assertEqual(result["savings"], Decimal("90"))

    def test_without_pulp_greedy_is_used_and_labelled(self):
        SustainabilityProject.objects.create(site=self.site, name="A", budget_tnd=10, expected_savings_m3=5)
        with mock.patch.dict("sys.modules", {"pulp": None}):
            result = optimize_projects(SustainabilityProject.objects.all(), 100)
        self.assertEqual(result["solver"], "greedy-fallback")

    def test_pdf_is_real_or_an_explicit_error(self):
        user = User.objects.create_superuser("admin", "a@example.tn", "x-Pass-12345")
        self.client.force_login(user)
        report = AuditReport.objects.create(site=self.site, period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
                                            snapshot={f"key_{i}": i for i in range(60)})  # plusieurs pages
        response = self.client.get(reverse("sustainability:audit_pdf", args=[report.pk]))
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 1000)  # plus le faux PDF vide d'avant
        with mock.patch("sustainability.views.render_audit_pdf", side_effect=PdfUnavailable("ReportLab absent")):
            response = self.client.get(reverse("sustainability:audit_pdf", args=[report.pk]), follow=True)
        self.assertRedirects(response, reverse("sustainability:audit_list"))
        self.assertContains(response, "ReportLab absent")


class TrainModelsCommandTests(MLTestCase):
    def test_command_runs_on_demo_data(self):
        call_command("seed_demo", verbosity=0)
        out = StringIO()
        call_command("train_models", stdout=out)
        self.assertIn("Terminé", out.getvalue())
        self.assertFalse(MeterReading.objects.filter(meter__readings__isnull=False, model_version="").exclude(
            pk__in=[m.readings.order_by("recorded_at").first().pk for m in WaterMeter.objects.all() if m.readings.exists()]
        ).exists())
