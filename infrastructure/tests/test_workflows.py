"""
Tests de bout en bout du scénario du dossier de validation et des pages des 4 modules.

1. ENREGISTRER : un relevé (saisi ou importé en CSV) est enregistré et analysé.
2. ENQUÊTER    : une consommation anormale ouvre un incident, complété puis résolu.
3. RÉPARER     : l'équipement suspecté reçoit une intervention.
4. MESURER     : bilan des compteurs, cibles, projets, bénéfices et audit.

Le dernier test parcourt TOUTES les pages de l'application avec un marqueur de variable invalide :
une page en erreur ou un champ mal nommé dans un gabarit fait échouer le test.
"""
import copy
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from consumption.models import MeterReading, WaterBill, WaterMeter
from consumption.services.anomaly import analyze
from infrastructure.models import MaintenanceWork, Site
from quality_leaks.models import AlertRule, LeakIncident, WaterQualityTest
from sustainability.models import AuditReport, ConservationTarget, MeasuredBenefit, OptimizationRun, SustainabilityProject

from .factories import make_pipe, make_site, make_tech, make_zone


def aware(d):
    return timezone.make_aware(datetime(d.year, d.month, d.day))


def monthly(meter, rates, start=date(2025, 1, 1)):
    """Relevés mensuels cumulés : rates[i] = m³/jour pendant le mois i."""
    d, index = start, Decimal("1000")
    MeterReading.objects.create(meter=meter, recorded_at=aware(d), index_m3=index)
    for rate in rates:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        index += Decimal(str(round(rate * (nxt - d).days, 3)))
        MeterReading.objects.create(meter=meter, recorded_at=aware(nxt), index_m3=index)
        d = nxt
    return meter


class Base(TestCase):
    def setUp(self):
        self.site = make_site()
        self.zone = make_zone(self.site)
        self.admin = User.objects.create_superuser("admin", "admin@example.tn", "x-Pass-12345")
        self.client.force_login(self.admin)

    def meter(self, serial="M-1", zone=None):
        return WaterMeter.objects.create(zone=zone or self.zone, serial_number=serial, customer_category="public")


class LeakWorkflowTests(Base):
    def test_spike_on_latest_reading_opens_one_incident_then_it_is_resolved(self):
        steady = [10, 10.3, 9.7] * 4
        leak = self.meter("M-LEAK")
        monthly(leak, steady[:11] + [30])            # dernier mois × 3 : fuite
        monthly(self.meter("M-A"), steady)
        monthly(self.meter("M-B"), [5, 5.2, 4.9] * 4)
        result = analyze()
        self.assertEqual(result["incidents_opened"], 1)
        incident = LeakIncident.objects.get()
        self.assertEqual(incident.meter, leak)
        self.assertEqual(incident.trigger_reading, leak.readings.order_by("recorded_at").last())
        self.assertEqual(incident.trigger_evidence["source"], "detection_fuites")
        self.assertIn("M-LEAK", incident.description)
        # Nouvelle analyse : pas de doublon tant que l'incident est ouvert.
        self.assertEqual(analyze()["incidents_opened"], 0)
        # Le technicien complète puis résout l'incident.
        pipe, tech = make_pipe(self.zone), make_tech()
        response = self.client.post(reverse("quality_leaks:incident_update", args=[incident.pk]), {
            "meter": leak.pk, "technician": tech.pk, "suspected_pipe": pipe.pk, "position_on_pipe": "0.3",
            "description": incident.description})
        self.assertRedirects(response, incident.get_absolute_url())
        incident.refresh_from_db()
        self.assertEqual((incident.technician, incident.suspected_pipe, incident.meter), (tech, pipe, leak))
        page = self.client.get(incident.get_absolute_url())
        self.assertContains(page, "Planifier la réparation")
        self.assertContains(page, f"?pipe={pipe.pk}&amp;type=corrective")
        self.client.post(reverse("quality_leaks:incident_resolve", args=[incident.pk]))
        incident.refresh_from_db()
        self.assertEqual(incident.status, "resolved")
        self.assertIsNotNone(incident.resolved_at)

    def test_old_spike_is_flagged_but_does_not_open_an_incident(self):
        steady = [10, 10.3, 9.7] * 4
        monthly(self.meter("M-OLD"), steady[:5] + [30] + steady[6:])
        monthly(self.meter("M-A"), steady)
        result = analyze()
        self.assertGreaterEqual(result["anomalies"], 1)
        self.assertEqual(result["incidents_opened"], 0)

    def test_incident_references_are_unique_within_the_same_second(self):
        for _ in range(5):
            LeakIncident.objects.create(description="x")
        self.assertEqual(LeakIncident.objects.values("reference").distinct().count(), 5)

    def test_new_reading_view_reports_a_leak_and_returns_to_the_meter(self):
        meter = monthly(self.meter(), [10, 10.2, 9.9, 10.1])
        last = meter.readings.order_by("recorded_at").last()
        response = self.client.post(reverse("consumption:reading_create"), {
            "meter": meter.pk, "recorded_at": (last.recorded_at + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M"),
            "index_m3": str(last.index_m3 + 900), "source": "manual"}, follow=True)
        self.assertRedirects(response, reverse("consumption:meter_detail", args=[meter.pk]))
        self.assertContains(response, "fuite possible")
        self.assertTrue(LeakIncident.objects.exists())


class CsvImportTests(Base):
    CSV = "recorded_at,index_m3\n2026-01-01T00:00:00+01:00,100\n2026-02-01T00:00:00+01:00,130\n2026-03-01T00:00:00+01:00,160\n"

    def post(self, meter, content):
        upload = StringIO(content)
        upload.name = "r.csv"
        return self.client.post(reverse("consumption:meter_import", args=[meter.pk]), {"file": upload}, follow=True)

    def test_same_file_twice_imports_nothing_the_second_time(self):
        meter = self.meter()
        self.assertContains(self.post(meter, self.CSV), "3 relevé(s) importé(s)")
        self.assertContains(self.post(meter, self.CSV), "0 relevé(s) importé(s)")
        self.assertEqual(meter.readings.count(), 3)

    def test_conflicting_or_decreasing_or_bad_files_are_refused_without_writing(self):
        meter = self.meter()
        self.post(meter, self.CSV)
        cases = {
            "autre index": "recorded_at,index_m3\n2026-02-01T00:00:00+01:00,131\n",
            "augmenter": "recorded_at,index_m3\n2026-04-01T00:00:00+01:00,150\n",
            "invalide": "recorded_at,index_m3\npas-une-date,12\n",
            "colonnes": "date,index\n2026-04-01,170\n",
        }
        for expected, content in cases.items():
            with self.subTest(expected=expected):
                response = self.post(meter, content)
                self.assertEqual(response.status_code, 200)  # plus de page d'erreur brute ni d'erreur serveur
                self.assertContains(response, "Import refusé")
                self.assertContains(response, expected)
        self.assertEqual(meter.readings.count(), 3)


class BillAndBalanceTests(Base):
    def test_bill_volume_is_calculated_from_readings_when_left_empty(self):
        meter = monthly(self.meter(), [10, 10, 10])  # janvier → avril 2025
        response = self.client.post(reverse("consumption:bill_create"), {
            "meter": meter.pk, "period_start": "2025-01-01", "period_end": "2025-03-01", "volume_m3": ""})
        self.assertRedirects(response, reverse("consumption:bill_list"))
        bill = WaterBill.objects.get()
        self.assertEqual(bill.volume_m3, Decimal("590.000"))  # 31 + 28 jours × 10 m³

    def test_bill_without_enough_readings_asks_for_the_volume(self):
        meter = self.meter()
        response = self.client.post(reverse("consumption:bill_create"), {
            "meter": meter.pk, "period_start": "2025-01-01", "period_end": "2025-03-01", "volume_m3": ""})
        self.assertContains(response, "Pas assez de relevés")
        self.assertFalse(WaterBill.objects.exists())

    def test_water_balance_per_zone_and_unmetered_zones(self):
        other = make_zone(self.site, code="Z-02", name="Cantine")
        empty = make_zone(self.site, code="Z-03", name="Jardin")
        monthly(self.meter("M-1"), [10, 10, 10])
        monthly(self.meter("M-2", zone=other), [2, 2, 2])
        balance = self.site.calculate_water_balance(aware(date(2025, 1, 1)), aware(date(2025, 4, 1)))
        self.assertEqual(balance["total_m3"], Decimal("1080.000"))  # (10 + 2) × 90 jours
        self.assertEqual([z["volume_m3"] for z in balance["zones"]], [Decimal("900.000"), Decimal("180.000")])
        self.assertEqual(balance["unmetered_zones"], [empty])
        self.assertIsNone(balance["losses_m3"])
        page = self.client.get(self.site.get_absolute_url())
        self.assertContains(page, "Consommation mesurée")
        self.assertContains(page, "Sans compteur")


class QualityWorkflowTests(Base):
    def setUp(self):
        super().setUp()
        AlertRule.objects.create(name="Turbidité critique", parameter="turbidity_ntu", operator="gt", threshold=5, severity="critical")
        AlertRule.objects.create(name="Chlore bas", parameter="chlorine_mg_l", operator="lt", threshold="0.2", severity="warning")

    def create_test(self, **values):
        data = {"zone": self.zone.pk, "sampled_at": "2026-11-01T09:00", "laboratory": "Labo", "ph": "7.2",
                "turbidity_ntu": "1", "chlorine_mg_l": "0.3", "conductivity_us_cm": "800"}
        data.update(values)
        return self.client.post(reverse("quality_leaks:test_create"), data, follow=True)

    def test_critical_rule_opens_an_incident(self):
        response = self.create_test(turbidity_ntu="12")
        self.assertContains(response, "Règle critique enfreinte")
        incident = LeakIncident.objects.get()
        self.assertEqual(incident.rule.name, "Turbidité critique")
        self.assertEqual(incident.trigger_test, WaterQualityTest.objects.get())
        self.assertEqual(Decimal(incident.trigger_evidence["measurements"]["turbidity_ntu"]), 12)

    def test_warning_rule_only_warns_with_a_link(self):
        response = self.create_test(chlorine_mg_l="0.05")
        self.assertContains(response, "Chlore bas")
        self.assertContains(response, "Ouvrir un incident")
        self.assertFalse(LeakIncident.objects.exists())

    def test_compliant_sample_creates_nothing(self):
        self.assertContains(self.create_test(), "aucune règle d&#x27;alerte enfreinte")
        self.assertFalse(LeakIncident.objects.exists())

    def test_incident_form_needs_a_source_and_uses_a_meter_list(self):
        page = self.client.get(reverse("quality_leaks:incident_create"))
        self.assertContains(page, 'name="meter"')
        self.assertNotContains(page, "meter_content_type")
        response = self.client.post(reverse("quality_leaks:incident_create"), {"description": "?", "position_on_pipe": "0.5"})
        self.assertContains(response, "Indiquez la source")
        meter = self.meter()
        response = self.client.post(reverse("quality_leaks:incident_create"), {"meter": meter.pk, "description": "Fuite visible", "position_on_pipe": "0.5"})
        self.assertEqual(LeakIncident.objects.get().meter, meter)


class SustainabilityWorkflowTests(Base):
    def test_audit_uses_the_requested_period_and_site(self):
        meter = monthly(self.meter(), [10, 10, 10, 10])           # janvier → mai 2025
        monthly(WaterMeter.objects.create(zone=make_zone(make_site(code="AUTRE")), serial_number="M-X"), [99, 99])
        response = self.client.post(reverse("sustainability:audit_report"),
                                    {"site": self.site.pk, "period_start": "2025-02-01", "period_end": "2025-03-31"})
        report = AuditReport.objects.get()
        self.assertRedirects(response, reverse("sustainability:audit_pdf", args=[report.pk]), fetch_redirect_response=False)
        self.assertEqual(report.site, self.site)
        self.assertAlmostEqual(report.snapshot["consumption_m3"], 280.0)  # février + mars, compteur du site seulement
        self.assertTrue(self.client.get(reverse("sustainability:audit_pdf", args=[report.pk])).content.startswith(b"%PDF"))
        self.assertContains(self.client.post(reverse("sustainability:audit_report"),
                                             {"period_start": "2025-03-01", "period_end": "2025-01-01"}), "postérieure")
        self.assertEqual(meter.readings.count(), 5)

    def test_target_progress_project_benefit_and_delete(self):
        monthly(self.meter(), [10, 10, 10])
        target = ConservationTarget.objects.create(site=self.site, name="T1", period_start=date(2025, 1, 1), period_end=date(2025, 4, 1),
                                                   baseline_m3=1000, target_reduction_percent=20)
        page = self.client.get(target.get_absolute_url())
        self.assertEqual(page.context["measured_m3"], 900.0)
        self.assertEqual(page.context["progress_pct"], 50.0)  # 100 m³ économisés sur 200 visés
        project = SustainabilityProject.objects.create(site=self.site, name="Récupération pluie", budget_tnd=5000,
                                                       expected_savings_m3=800, expected_annual_savings_tnd=1200)
        self.assertContains(self.client.get(project.get_absolute_url()), "reste une estimation")
        form = self.client.get(reverse("sustainability:benefit_create") + f"?project={project.pk}")
        self.assertEqual(form.context["form"].initial["project"], project.pk)
        self.client.post(reverse("sustainability:benefit_create"), {"project": project.pk, "period_start": "2025-06-01",
                         "period_end": "2025-05-01", "measured_savings_m3": "10", "measured_savings_tnd": "5"})
        self.assertFalse(MeasuredBenefit.objects.exists())  # fin avant début : refusé
        self.client.post(reverse("sustainability:project_delete", args=[project.pk]))
        self.assertFalse(SustainabilityProject.objects.exists())

    def test_dashboard_leaks_are_filtered_by_site(self):
        other = make_site(code="AUTRE")
        LeakIncident.objects.create(suspected_pipe=make_pipe(make_zone(other), reference="P-X"), description="ailleurs")
        page = self.client.get(reverse("sustainability:dashboard") + f"?site={self.site.pk}")
        self.assertEqual(page.context["metrics"]["active_leaks"], 0)
        page = self.client.get(reverse("sustainability:dashboard") + f"?site={other.pk}")
        self.assertEqual(page.context["metrics"]["active_leaks"], 1)


class ReadOnlyInterfaceTests(Base):
    def test_buttons_match_permissions(self):
        reader = User.objects.create_user("reader", password="x-Pass-12345")
        pages = [reverse(n) for n in ("consumption:dashboard", "consumption:meter_list", "quality_leaks:dashboard",
                                      "quality_leaks:incident_list", "sustainability:dashboard", "sustainability:project_list",
                                      "infrastructure:dashboard")]
        hidden = ["Nouveau compteur", "Nouvel incident", "Optimiser le budget", "Nouveau projet", "Nouveau relevé"]
        self.client.force_login(reader)
        for url in pages:
            html = self.client.get(url).content.decode()
            for label in hidden:
                self.assertNotIn(label, html, f"{label} visible on {url}")
        reader.user_permissions.add(Permission.objects.get(codename="add_watermeter"))
        reader = User.objects.get(pk=reader.pk)
        self.client.force_login(reader)
        self.assertContains(self.client.get(reverse("consumption:meter_list")), "Nouveau compteur")


MARKER = "§INVALID§"


def templates_with_marker():
    templates = copy.deepcopy(settings.TEMPLATES)
    templates[0]["OPTIONS"]["string_if_invalid"] = MARKER
    return templates


class WholeApplicationCrawlTests(TestCase):
    """Toutes les pages, toutes les données : aucune erreur serveur, aucun champ inexistant dans les gabarits."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        call_command("seed_tekup", verbosity=0)
        cls.admin = User.objects.create_superuser("admin", "admin@example.tn", "x-Pass-12345")
        analyze()
        site = Site.objects.get(code="SIT-MNB-001")
        pipe = site.zones.first().waterpipes.first()
        meter = WaterMeter.objects.filter(zone__site=site).first()
        LeakIncident.objects.create(meter=meter, suspected_pipe=pipe, technician=make_tech("TEC-CRAWL"), description="Fuite au raccord")
        AlertRule.objects.get_or_create(name="Turbidité", defaults={"parameter": "turbidity_ntu", "operator": "gt", "threshold": 5, "severity": "critical"})
        project = SustainabilityProject.objects.create(site=site, name="Projet crawl", budget_tnd=1000, expected_savings_m3=100, expected_annual_savings_tnd=300)
        MeasuredBenefit.objects.create(project=project, period_start=date(2026, 1, 1), period_end=date(2026, 3, 31), measured_savings_m3=20)
        ConservationTarget.objects.get_or_create(site=site, name="Cible crawl", defaults={"period_start": date(2026, 1, 1), "period_end": date(2026, 6, 30),
                                                 "baseline_m3": 500, "target_reduction_percent": 10})
        OptimizationRun.objects.create(budget_tnd=5000, solver="PuLP", recommendations=[{"id": project.pk, "name": project.name, "cost_tnd": "1000", "savings_m3": "100"}])
        AuditReport.objects.create(period_start=date(2026, 1, 1), period_end=date(2026, 3, 31), snapshot={"consumption_m3": 12.5})
        MaintenanceWork.objects.create(technician=make_tech("TEC-CRAWL2"), pipe=pipe, scheduled_at=timezone.now())

    def crawl(self, user):
        """Suit tous les liens internes ; renvoie (pages vues, problèmes)."""
        self.client.force_login(user)
        start = ["/infrastructure/", "/consommation/", "/qualite-fuites/", "/durabilite/", "/comptes/", "/infrastructure/sites/"]
        seen, queue, problems = set(start), list(start), []
        with override_settings(TEMPLATES=templates_with_marker()):
            while queue and len(seen) < 600:
                url = queue.pop(0)
                response = self.client.get(url)
                if response.status_code >= 400 and response.status_code != 405:
                    problems.append(f"{response.status_code} {url}")
                    continue
                if response.get("Content-Type", "").startswith("text/html") and response.status_code == 200:
                    html = response.content.decode()
                    if MARKER in html:
                        context = html[max(0, html.index(MARKER) - 120):html.index(MARKER) + 20]
                        problems.append(f"invalid variable on {url}: …{context}…")
                    for link in re.findall(r'href="(/[^"#?]*(?:\?[^"#]*)?)"', html):
                        link = link.replace("&amp;", "&")
                        if not re.match(r"^/(admin|static|media|deconnexion)", link) and link != "/" and link not in seen:
                            seen.add(link)
                            queue.append(link)
        return seen, problems

    def test_every_page_renders_without_errors_or_unknown_fields(self):
        seen, problems = self.crawl(self.admin)
        self.assertGreater(len(seen), 150)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_read_only_user_never_sees_a_link_to_a_forbidden_page(self):
        reader = User.objects.create_user("reader", password="x-Pass-12345")
        seen, problems = self.crawl(reader)
        self.assertGreater(len(seen), 60)  # moins que l'admin : formulaires et boutons interdits sont masqués
        self.assertEqual(problems, [], "\n".join(problems))
