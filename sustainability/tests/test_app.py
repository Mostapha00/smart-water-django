from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from infrastructure.models import Site, WaterZone
from sustainability.models import ConservationTarget, SustainabilityProject
from sustainability.services.optimization import optimize_projects


class SustainabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="manager", password="safe-pass-123")
        self.site = Site.objects.create(code="SUS-01", name="Demo", governorate="Tunis")
        WaterZone.objects.create(site=self.site, code="Z1", name="Atelier")
        self.client.force_login(self.user)

    def test_target_calculates_reduced_volume(self):
        target = ConservationTarget.objects.create(
            site=self.site, name="2026", period_start="2026-01-01", period_end="2026-12-31",
            baseline_m3=1000, target_reduction_percent=15,
        )
        self.assertEqual(target.target_m3, Decimal("850.000"))

    def test_greedy_optimizer_respects_budget(self):
        SustainabilityProject.objects.create(site=self.site, name="A", budget_tnd=100, expected_savings_m3=50)
        SustainabilityProject.objects.create(site=self.site, name="B", budget_tnd=200, expected_savings_m3=200)
        result = optimize_projects(SustainabilityProject.objects.all(), 200)
        self.assertLessEqual(result["total_cost"], Decimal("200"))
        self.assertEqual(result["projects"][0].name, "B")

    def test_authenticated_dashboard_and_audit_pdf(self):
        self.assertEqual(self.client.get(reverse("sustainability:dashboard")).status_code, 200)
        response = self.client.post(reverse("sustainability:audit_report"), {})
        self.assertEqual(response.status_code, 302)
        pdf = self.client.get(response.url)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
