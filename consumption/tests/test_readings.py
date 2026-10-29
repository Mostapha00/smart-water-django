from datetime import date
from decimal import Decimal
import io

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase

from consumption.models import MeterReading, WaterMeter
from .factories import meter, reading


class ReadingTests(TestCase):
    def setUp(self):
        self.meter = meter()

    def test_first_reading_is_not_a_consumption(self):
        first = reading(self.meter, date(2026, 1, 1), 100)
        self.assertIsNone(first.calculate_volume())
        second = reading(self.meter, date(2026, 1, 2), 103.125)
        self.assertEqual(second.calculate_volume(), Decimal("3.125"))

    def test_out_of_order_insert_checks_both_neighbours(self):
        reading(self.meter, date(2026, 1, 1), 100)
        reading(self.meter, date(2026, 1, 3), 110)
        with self.assertRaises(ValidationError):
            reading(self.meter, date(2026, 1, 2), 111)
        with self.assertRaises(ValidationError):
            reading(self.meter, date(2026, 1, 2), 99)
        reading(self.meter, date(2026, 1, 2), 105)

    def test_duplicate_timestamp_and_negative_index_are_rejected(self):
        reading(self.meter, date(2026, 1, 1), 100)
        for index in (101, -1):
            with self.subTest(index=index), self.assertRaises(ValidationError):
                reading(self.meter, date(2026, 1, 1), index)

    def test_reading_cannot_predate_installation(self):
        with self.assertRaises(ValidationError):
            reading(self.meter, date(2024, 1, 1), 1)

    def test_installation_cannot_move_after_a_reading(self):
        reading(self.meter, date(2026, 1, 1), 100)
        self.meter.installed_on = date(2026, 2, 1)
        with self.assertRaises(ValidationError):
            self.meter.save()

    def test_meter_aggregates_but_owns_readings(self):
        reading(self.meter, date(2026, 1, 1), 100)
        with self.assertRaises(ProtectedError):
            self.meter.zone.delete()
        self.meter.delete()
        self.assertEqual(MeterReading.objects.count(), 0)

    def test_csv_can_be_unsorted_and_reimported(self):
        text = "\ufeffrecorded_at,index_m3\n2026-01-03T00:00:00+01:00,110\n2026-01-01T00:00:00+01:00,100\n2026-01-02T00:00:00+01:00,105\n"
        self.assertEqual(self.meter.import_csv_readings(io.StringIO(text)), {"created": 3, "skipped": 0})
        self.assertEqual(self.meter.import_csv_readings(io.StringIO(text)), {"created": 0, "skipped": 3})

    def test_invalid_csv_has_no_partial_writes(self):
        for last in ("bad", "NaN", "Infinity", "-1", "99", "100.0001"):
            text = f"recorded_at,index_m3\n2026-01-01T00:00:00+01:00,100\n2026-01-02T00:00:00+01:00,{last}\n"
            with self.subTest(last=last), self.assertRaises(ValidationError):
                self.meter.import_csv_readings(io.StringIO(text))
            self.assertEqual(self.meter.readings.count(), 0)

    def test_csv_conflict_does_not_change_existing_index(self):
        reading(self.meter, date(2026, 1, 1), 100)
        with self.assertRaises(ValidationError):
            self.meter.import_csv_readings(io.StringIO("recorded_at,index_m3\n2026-01-01T00:00:00,101\n2026-01-02T00:00:00,105"))
        self.assertEqual(self.meter.readings.count(), 1)
        self.assertEqual(self.meter.readings.get().index_m3, Decimal("100"))

    def test_csv_rejects_bad_headers_and_encoding(self):
        for file in (io.StringIO("date,index\n2026-01-01,1"), io.BytesIO(b"\xff\xfe"), io.StringIO("recorded_at,index_m3\n")):
            with self.assertRaises(ValidationError):
                self.meter.import_csv_readings(file)

    def test_new_reading_invalidates_old_forecast(self):
        WaterMeter.objects.filter(pk=self.meter.pk).update(forecast_m3=10, horizon_days=30, model_version="old")
        reading(self.meter, date(2026, 1, 1), 100)
        self.meter.refresh_from_db()
        self.assertIsNone(self.meter.forecast_m3)
        self.assertEqual(self.meter.model_version, "")
