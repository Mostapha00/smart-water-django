from datetime import date
import io
import json
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from consumption.models import MeterReading, WaterBill, WaterMeter
from .factories import meter, reading, tariff


class ApiTests(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(AQUAMIND_CONSUMPTION_MODEL_DIR=directory))
        self.admin = User.objects.create_superuser("student2", "student2@example.invalid", "test-password-123")
        self.client.force_login(self.admin)
        self.meter = meter()

    def url(self, name, *args):
        return reverse("consumption:" + name, args=args)

    def send(self, method, name, payload, *args):
        return getattr(self.client, method)(self.url(name, *args), json.dumps(payload), content_type="application/json")

    def test_login_and_model_permissions(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url("meter_list")).status_code, 401)
        user = User.objects.create_user("reader", password="test-password-123")
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url("meter_list")).status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="view_watermeter"))
        self.assertEqual(self.client.get(self.url("meter_list")).status_code, 200)
        self.assertEqual(self.send("post", "meter_list", {}).status_code, 403)

    def test_resource_discovery_and_readonly_fields(self):
        result = self.client.get(self.url("api_index"))
        self.assertEqual(result.status_code, 200)
        self.assertIn("readings", result.json()["api"])
        response = self.send("patch", "meter_detail", {"forecast_m3": 999}, self.meter.pk)
        self.assertEqual(response.status_code, 400)
        self.meter.refresh_from_db()
        self.assertIsNone(self.meter.forecast_m3)

    def test_meter_crud(self):
        response = self.send("post", "meter_list", {"zone": self.meter.zone_id, "serial_number": "M-002", "customer_category": "school", "installed_on": "2026-01-01"})
        self.assertEqual(response.status_code, 201, response.content)
        pk = response.json()["id"]
        self.assertTrue(response.json()["active"])
        self.assertEqual(self.send("patch", "meter_detail", {"active": False}, pk).status_code, 200)
        self.assertEqual(self.client.get(self.url("meter_detail", pk)).status_code, 200)
        self.assertEqual(self.client.delete(self.url("meter_detail", pk)).status_code, 200)
        self.assertEqual(self.client.get(self.url("meter_detail", pk)).status_code, 404)

    def test_invalid_fk_boolean_and_decimal_inputs_are_errors(self):
        cases = [
            ("meter_detail", {"zone": "invalid"}, self.meter.pk),
            ("meter_detail", {"active": "not-a-boolean"}, self.meter.pk),
        ]
        for name, payload, pk in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.send("patch", name, payload, pk).status_code, 400)
        response = self.send("post", "reading_list", {"meter": self.meter.pk, "recorded_at": "not-a-date", "index_m3": "bad"})
        self.assertEqual(response.status_code, 400)

    def test_json_must_be_an_object_with_finite_numbers(self):
        for value in ("[]", "null", '{"index_m3":NaN}', "{"):
            response = self.client.post(self.url("reading_list"), value, content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_reading_crud_and_consumption_endpoint(self):
        payload = {"meter": self.meter.pk, "recorded_at": "2026-01-01T00:00:00+01:00", "index_m3": "100.125"}
        first = self.send("post", "reading_list", payload)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertIsNone(first.json()["volume_m3"])
        payload.update(recorded_at="2026-01-02T00:00:00+01:00", index_m3="102.250")
        second = self.send("post", "reading_list", payload)
        self.assertEqual(second.json()["volume_m3"], "2.125")
        response = self.client.get(self.url("meter_consumption", self.meter.pk), {"start": "2026-01-01", "end": "2026-01-02"})
        self.assertEqual(response.json()["volume_m3"], "2.125")
        self.assertEqual(self.send("patch", "reading_detail", {"index_m3": "99"}, second.json()["id"]).status_code, 400)
        self.assertEqual(self.client.delete(self.url("reading_detail", second.json()["id"])).status_code, 200)

    def test_import_endpoint_and_permission(self):
        csv = b"recorded_at,index_m3\n2026-01-01T00:00:00+01:00,100\n2026-01-02T00:00:00+01:00,102\n"
        response = self.client.post(self.url("meter_import", self.meter.pk), {"file": SimpleUploadedFile("readings.csv", csv, content_type="text/csv")})
        self.assertEqual(response.json(), {"created": 2, "skipped": 0})
        self.assertEqual(self.client.get(self.url("meter_import", self.meter.pk)).status_code, 405)
        self.assertEqual(self.client.post(self.url("meter_import", self.meter.pk), {}).status_code, 400)

    def test_bill_creation_issue_and_freeze(self):
        reading(self.meter, date(2026, 1, 1), 100)
        reading(self.meter, date(2026, 4, 1), 130)
        tariff(); tariff("ONAS")
        response = self.send("post", "bill_list", {"meter": self.meter.pk, "period_start": "2026-01-01", "period_end": "2026-04-01"})
        self.assertEqual(response.status_code, 201, response.content)
        pk = response.json()["id"]
        self.assertEqual(self.client.get(self.url("bill_issue", pk)).status_code, 405)
        issued = self.client.post(self.url("bill_issue", pk))
        self.assertEqual(issued.status_code, 200, issued.content)
        self.assertIsNotNone(issued.json()["issued_at"])
        self.assertEqual(self.send("patch", "bill_detail", {"include_onas": False}, pk).status_code, 400)
        self.assertEqual(self.client.delete(self.url("bill_detail", pk)).status_code, 400)

    def test_forecast_endpoint_persists_labelled_result(self):
        reading(self.meter, date(2026, 1, 1), 100)
        reading(self.meter, date(2026, 1, 11), 120)
        result = self.send("post", "meter_forecast", {"horizon_days": 30}, self.meter.pk)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.json()["is_baseline"])
        self.assertEqual(result.json()["forecast_m3"], "60.000")

    def test_csrf_is_required_for_session_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.get(self.url("api_index"))
        csrf = response.json()["csrf_token"]
        url = self.url("meter_detail", self.meter.pk)
        self.assertEqual(client.patch(url, '{"active":false}', content_type="application/json").status_code, 403)
        response = client.patch(url, '{"active":false}', content_type="application/json", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.content)

    def test_existing_3d_contract_sees_student_2_data(self):
        reading(self.meter, date(2026, 1, 1), 100)
        response = self.client.get(reverse("infrastructure:site_maquette_json", args=[self.meter.zone.site_id]))
        self.assertEqual(response.status_code, 200)
        item = response.json()["meters"][0]
        self.assertEqual(item["serial_number"], "M-001")
        self.assertEqual(item["zone"], self.meter.zone_id)
        self.assertEqual(item["readings"][0][1], 100.0)

    def test_admin_pages_render_and_bill_add_calculates_amounts(self):
        reading(self.meter, date(2026, 1, 1), 100)
        reading(self.meter, date(2026, 4, 1), 130)
        tariff(); tariff("ONAS")
        for name in ("watermeter", "meterreading", "tariffband", "waterbill"):
            for action in ("changelist", "add"):
                self.assertEqual(self.client.get(reverse(f"admin:consumption_{name}_{action}")).status_code, 200)
        response = self.client.post(reverse("admin:consumption_waterbill_add"), {"meter": self.meter.pk, "period_start": "2026-01-01", "period_end": "2026-04-01", "include_onas": "on", "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WaterBill.objects.count(), 1)

    def test_demo_seed_is_idempotent(self):
        out = io.StringIO()
        call_command("seed_consumption", stdout=out)
        counts = (WaterMeter.objects.count(), MeterReading.objects.count())
        call_command("seed_consumption", stdout=out)
        self.assertEqual((WaterMeter.objects.count(), MeterReading.objects.count()), counts)
        self.assertIn("FICTIONAL", out.getvalue())
