from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from infrastructure.models import MaintenanceWork
from infrastructure.services.risk import baseline_risk, features

from .factories import make_pipe, make_pump, make_site, make_tech, make_zone


class SiteZoneTests(TestCase):
    def test_validate_structure_requires_a_zone(self):
        site = make_site()
        with self.assertRaises(ValidationError):
            site.validate_structure()
        make_zone(site)
        site.validate_structure()  # ne lève plus

    def test_zone_code_unique_per_site(self):
        site = make_site()
        make_zone(site, code="Z-01")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_zone(site, code="Z-01")
        make_zone(make_site(code="SIT-T-002"), code="Z-01")  # autorisé sur un autre site

    def test_deleting_site_deletes_zones(self):
        site = make_site()
        make_zone(site)
        site.delete()
        from infrastructure.models import WaterZone
        self.assertEqual(WaterZone.objects.count(), 0)

    def test_meter_coverage_uses_student_2_models(self):
        from datetime import date
        from consumption.models import WaterMeter

        zone = make_zone(make_site())
        with self.assertRaises(ValidationError):
            zone.validate_meter_coverage()
        WaterMeter.objects.create(zone=zone, serial_number="M-COVERAGE", customer_category="school", installed_on=date(2026, 1, 1))
        zone.validate_meter_coverage()


@override_settings(AQUAMIND_REPLACEMENT_COSTS={
    "pipe_tnd_per_m_per_100mm": {"PEHD": 60, "default": 80}, "pipe_install_tnd_per_m": 25,
    "pump_tnd_per_kw": 900, "pump_fixed_tnd": 600,
})
class ReplacementCostTests(TestCase):
    def test_pipe_cost(self):
        pipe = make_pipe(make_zone(make_site()), length_m=Decimal("10"), diameter_mm=50, material="PEHD")
        # 10 m × (60 × 0,5 + 25) = 550
        self.assertEqual(pipe.estimate_replacement_cost(), Decimal("550"))

    def test_unknown_material_uses_default(self):
        pipe = make_pipe(make_zone(make_site()), length_m=Decimal("10"), diameter_mm=100, material="Inconnu")
        self.assertEqual(pipe.estimate_replacement_cost(), Decimal("1050"))

    def test_pump_cost(self):
        pump = make_pump(make_zone(make_site()), power_kw=Decimal("2"))
        self.assertEqual(pump.estimate_replacement_cost(), Decimal("2400"))


class MaintenanceWorkTests(TestCase):
    def setUp(self):
        self.zone = make_zone(make_site())
        self.pipe = make_pipe(self.zone)
        self.pump = make_pump(self.zone)
        self.tech = make_tech()

    def work(self, **kw):
        return MaintenanceWork(technician=self.tech, scheduled_at=timezone.now(), **kw)

    def test_xor_rejects_two_targets(self):
        with self.assertRaises(ValidationError):
            self.work(pipe=self.pipe, pump=self.pump).full_clean()

    def test_xor_rejects_no_target(self):
        with self.assertRaises(ValidationError):
            self.work().full_clean()

    def test_xor_enforced_in_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.work(pipe=self.pipe, pump=self.pump).save()

    def test_single_target_is_valid(self):
        self.work(pipe=self.pipe).full_clean()
        self.work(pump=self.pump).full_clean()

    def test_close_corrective_puts_equipment_back_in_service(self):
        self.pump.status = "en_panne"
        self.pump.save()
        w = self.work(pump=self.pump, maintenance_type="corrective")
        w.save()
        w.close_work(cost_tnd=Decimal("250"))
        self.pump.refresh_from_db()
        self.assertEqual(self.pump.status, "en_service")
        self.assertFalse(w.is_open)
        self.assertEqual(w.cost_tnd, Decimal("250"))
        with self.assertRaises(ValidationError):
            w.close_work()

    def test_schedule_maintenance_from_technician(self):
        w = self.tech.schedule_maintenance(self.pipe, timezone.now(), "preventive", "Contrôle")
        self.assertEqual(w.pipe, self.pipe)
        self.assertIsNone(w.pump)


class RiskTests(TestCase):
    def test_predict_stores_value_version_and_date(self):
        pipe = make_pipe(make_zone(make_site()))
        risk = pipe.predict_failure_30d()
        pipe.refresh_from_db()
        self.assertTrue(Decimal("0") <= risk <= Decimal("1"))
        self.assertEqual(pipe.model_version, "baseline-0.1")
        self.assertIsNotNone(pipe.predicted_at)

    def test_broken_equipment_is_riskier(self):
        zone = make_zone(make_site())
        ok = make_pump(zone, reference="P-OK")
        ko = make_pump(zone, reference="P-KO", status="en_panne")
        self.assertGreater(baseline_risk(features(ko)), baseline_risk(features(ok)))
