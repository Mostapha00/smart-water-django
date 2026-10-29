from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from infrastructure.models import Site, WaterPipe, WaterPump, WaterZone

from .models import AlertRule, LeakIncident, WaterQualityTest


class QualityLeaksTests(TestCase):
    def setUp(self):
        self.site = Site.objects.create(code="S1", name="Site 1", governorate="Tunis")
        self.zone = WaterZone.objects.create(site=self.site, code="Z1", name="Zone 1")

    def test_classification_and_rule_evaluation(self):
        test = WaterQualityTest.objects.create(
            zone=self.zone, ph=Decimal("9.0"), turbidity_ntu=Decimal("2")
        )
        rule = AlertRule.objects.create(
            name="pH élevé", parameter="ph", operator="gt", threshold=Decimal("8.5")
        )
        self.assertEqual(test.classify_potability(), Decimal("0.5"))
        self.assertEqual(test.evaluate_rules(), [rule])

    def test_incident_target_is_xor(self):
        pipe = WaterPipe.objects.create(
            zone=self.zone, reference="P1", material="PVC", length_m=10, diameter_mm=50
        )
        pump = WaterPump.objects.create(
            zone=self.zone, reference="M1", power_kw=2, rated_flow_m3_h=10
        )
        incident = LeakIncident(suspected_pipe=pipe, suspected_pump=pump)
        with self.assertRaises(ValidationError):
            incident.full_clean()
