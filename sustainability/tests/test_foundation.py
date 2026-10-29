"""Phase 1 smoke tests: the module is installed, routed and database-backed."""

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse


class FoundationTests(TestCase):
    def test_app_is_installed(self):
        self.assertTrue(apps.is_installed('sustainability'))
        config = apps.get_app_config('sustainability')
        self.assertEqual(config.name, 'sustainability')

    def test_dashboard_url_resolves_and_renders(self):
        url = reverse('sustainability:dashboard')
        self.assertEqual(url, '/durabilite/')

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'sustainability/dashboard.html')
        self.assertTemplateUsed(response, 'sustainability/base.html')
        self.assertContains(response, 'Executive Dashboard')

    def test_dashboard_reports_real_database_vendor(self):
        response = self.client.get(reverse('sustainability:dashboard'))

        self.assertIn('foundation', response.context)
        self.assertEqual(response.context['foundation']['db_vendor'], connection.vendor)
        self.assertIn(connection.vendor, {'sqlite', 'postgresql'})

    def test_dashboard_contains_no_pretend_metrics(self):
        """The scaffold page must not display invented KPI values."""
        response = self.client.get(reverse('sustainability:dashboard'))

        self.assertNotIn('m³', response.content.decode())
