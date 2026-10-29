from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.test import TestCase

from infrastructure.models import Site, WaterZone

from .models import MeterReading, TariffBand, WaterBill, WaterMeter


class ConsumptionModelTests(TestCase):
    def setUp(self):
        site = Site.objects.create(code="S1", name="Site", governorate="Tunis")
        zone = WaterZone.objects.create(site=site, code="Z1", name="Zone")
        self.meter = WaterMeter.objects.create(zone=zone, serial_number="M-1")

    def test_import_volume_forecast_and_anomaly(self):
        rows = StringIO("recorded_at,index_m3\n2026-01-01T00:00:00+00:00,100\n"
                        "2026-02-01T00:00:00+00:00,110\n2026-03-01T00:00:00+00:00,120\n"
                        "2026-04-01T00:00:00+00:00,150\n")
        imported = self.meter.import_csv_readings(rows)
        self.assertEqual(len(imported), 4)
        self.assertEqual(self.meter.forecast_consumption(), Decimal("16.475"))
        self.assertTrue(imported[-1].detect_anomaly())
        self.assertEqual(imported[-1].calculate_volume(), Decimal("30"))

    def test_cumulative_indexes_cannot_decrease(self):
        first = MeterReading.objects.create(
            meter=self.meter, recorded_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc), index_m3=10
        )
        reading = MeterReading(meter=self.meter, recorded_at=datetime(2026, 1, 2, tzinfo=dt_timezone.utc), index_m3=9)
        with self.assertRaises(ValidationError):
            reading.full_clean()
        self.assertIsNone(first.calculate_volume())

    def test_bill_uses_tariff_snapshot(self):
        band = TariffBand.objects.create(service="SONEDE", customer_category=self.meter.customer_category,
                                         valid_from="2026-01-01", lower_bound_m3=0,
                                         upper_bound_m3=100, price_per_m3_tnd="1.5", fixed_fee_tnd="2")
        bill = WaterBill.objects.create(meter=self.meter, sonede_band=band, period_start="2026-01-01",
                                        period_end="2026-01-31", volume_m3=10)
        self.assertEqual(bill.calculate_amounts(), Decimal("17.000"))
        self.assertEqual(bill.tariff_snapshot["sonede"]["price_per_m3_tnd"], "1.500")
