import json

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from infrastructure.models import MaintenanceWork, Site

from .factories import make_pipe, make_pump, make_site, make_tech, make_zone


class AccessTests(TestCase):
    def test_login_required(self):
        r = self.client.get(reverse("infrastructure:site_list"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r.url)

    def test_read_only_user_cannot_create(self):
        User.objects.create_user("lecteur", password="x-Pass-12345")
        self.client.login(username="lecteur", password="x-Pass-12345")
        self.assertEqual(self.client.get(reverse("infrastructure:site_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("infrastructure:site_create")).status_code, 403)


class CrudTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.tn", "x-Pass-12345")
        self.client.force_login(self.admin)

    def test_create_site_then_zone(self):
        r = self.client.post(reverse("infrastructure:site_create"), {
            "code": "SIT-NEW", "name": "Nouveau", "site_type": "usine", "governorate": "Sfax", "address": ""})
        site = Site.objects.get(code="SIT-NEW")
        self.assertRedirects(r, site.get_absolute_url())
        r = self.client.post(reverse("infrastructure:zone_create"), {
            "site": site.pk, "code": "Z-01", "name": "Atelier", "usage": "Process", "service_pressure_bar": "3",
            "display_kind": "building", "floors": 1})
        self.assertEqual(site.zones.count(), 1)

    def test_pages_render(self):
        zone = make_zone(make_site())
        pipe, pump = make_pipe(zone), make_pump(zone)
        w = MaintenanceWork.objects.create(technician=make_tech(), pipe=pipe, scheduled_at="2026-01-01T10:00+01:00")
        for url in [
            reverse("infrastructure:site_list"), reverse("infrastructure:site_detail", args=[zone.site_id]),
            reverse("infrastructure:pipe_detail", args=[pipe.pk]), reverse("infrastructure:pump_detail", args=[pump.pk]),
            reverse("infrastructure:work_list"), reverse("infrastructure:work_detail", args=[w.pk]),
            reverse("infrastructure:work_create") + f"?pipe={pipe.pk}", reverse("infrastructure:site_maquette", args=[zone.site_id]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_work_form_rejects_two_targets(self):
        zone = make_zone(make_site())
        r = self.client.post(reverse("infrastructure:work_create"), {
            "technician": make_tech().pk, "pipe": make_pipe(zone).pk, "pump": make_pump(zone).pk,
            "maintenance_type": "corrective", "scheduled_at": "2026-10-25T09:00"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "exactement une cible")
        self.assertEqual(MaintenanceWork.objects.count(), 0)

    def test_close_work(self):
        zone = make_zone(make_site())
        pump = make_pump(zone, status="en_panne")
        w = MaintenanceWork.objects.create(technician=make_tech(), pump=pump, maintenance_type="corrective", scheduled_at="2026-01-01T10:00+01:00")
        self.client.post(reverse("infrastructure:work_close", args=[w.pk]), {"cost_tnd": "120", "work_summary": "OK"})
        w.refresh_from_db(); pump.refresh_from_db()
        self.assertIsNotNone(w.completed_at)
        self.assertEqual(pump.status, "en_service")

    def test_zone_with_equipment_cannot_be_deleted(self):
        zone = make_zone(make_site())
        make_pipe(zone)
        r = self.client.post(reverse("infrastructure:zone_delete", args=[zone.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(type(zone).objects.filter(pk=zone.pk).exists())


class MaquetteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "a@example.tn", "x-Pass-12345")
        self.client.force_login(self.admin)
        call_command("seed_demo", verbosity=0)
        self.site = Site.objects.get(code="SIT-MNB-001")

    def test_json_contract(self):
        data = self.client.get(reverse("infrastructure:site_maquette_json", args=[self.site.pk])).json()
        self.assertEqual(set(data), {"site", "today", "can_edit", "urls", "technicians", "zones", "equipment", "works", "meters", "incidents"})
        self.assertEqual(len(data["zones"]), 3)
        self.assertEqual(len(data["equipment"]), 6)
        self.assertEqual(sum(1 for e in data["equipment"] if e.get("role") == "main"), 1)
        self.assertTrue(data["can_edit"])
        self.assertIn("__id__", data["urls"]["zone_position"])
        for w in data["works"]:
            self.assertTrue((w["pipe"] is None) != (w["pump"] is None))

    def test_save_zone_position(self):
        zone = self.site.zones.first()
        url = reverse("infrastructure:zone_position", args=[zone.pk])
        r = self.client.post(url, json.dumps({"pos_x": 4.5, "pos_y": -3}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        zone.refresh_from_db()
        self.assertEqual(float(zone.pos_x), 4.5)
        bad = self.client.post(url, json.dumps({"pos_x": "abc"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_position_needs_permission(self):
        User.objects.create_user("lecteur", password="x-Pass-12345")
        self.client.login(username="lecteur", password="x-Pass-12345")
        zone = self.site.zones.first()
        r = self.client.post(reverse("infrastructure:zone_position", args=[zone.pk]), "{}", content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_seed_is_idempotent(self):
        call_command("seed_demo", verbosity=0)
        self.assertEqual(Site.objects.filter(code="SIT-MNB-001").count(), 1)
        self.assertEqual(MaintenanceWork.objects.count(), 3)
