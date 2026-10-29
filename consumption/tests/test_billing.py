from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase

from consumption.models import TariffBand, WaterBill
from consumption.services.billing import quote_service
from .factories import bill, meter, reading, tariff

START, END = date(2026, 1, 1), date(2026, 4, 1)


class TariffTests(TestCase):
    def test_global_rate_and_fixed_fee(self):
        tariff(upper_bound_m3=20, price_per_m3_tnd=Decimal("0.5"))
        second = tariff(lower_bound_m3=20, price_per_m3_tnd=Decimal("1.0"))
        reached, amount, snapshot = quote_service("SONEDE", "school", START, END, Decimal("30"))
        self.assertEqual(reached, second)
        self.assertEqual(amount, Decimal("33.000"))
        self.assertEqual(len(snapshot["bands"]), 1)

    def test_marginal_bands_charge_fixed_fee_once(self):
        tariff(upper_bound_m3=20, price_per_m3_tnd=Decimal("0.5"), calculation_mode="marginal")
        tariff(lower_bound_m3=20, price_per_m3_tnd=Decimal("1.0"), calculation_mode="marginal")
        _, amount, snapshot = quote_service("SONEDE", "school", START, END, Decimal("30"))
        self.assertEqual(amount, Decimal("23.000"))
        self.assertEqual(snapshot["fixed_tnd"], "3.000")

    def test_zero_consumption_still_has_one_fixed_fee(self):
        tariff()
        self.assertEqual(quote_service("SONEDE", "school", START, END, Decimal("0"))[1], Decimal("3.000"))

    def test_short_period_prorates_bounds_and_fee(self):
        tariff(upper_bound_m3=Decimal("90"), price_per_m3_tnd=Decimal("0.5"))
        second = tariff(lower_bound_m3=Decimal("90"), price_per_m3_tnd=Decimal("1.0"))
        reached, amount, _ = quote_service("SONEDE", "school", START, date(2026, 1, 31), Decimal("30"))
        self.assertEqual(reached, second)  # Half-open normalized bounds: 30/30*90 = 90.
        self.assertEqual(amount, Decimal("31.000"))

    def test_overlapping_band_is_rejected(self):
        tariff(upper_bound_m3=20)
        with self.assertRaises(ValidationError):
            tariff(lower_bound_m3=10, upper_bound_m3=30)

    def test_gaps_and_mixed_modes_fail_instead_of_guessing(self):
        tariff(upper_bound_m3=20)
        second = tariff(lower_bound_m3=21)
        with self.assertRaises(ValidationError):
            quote_service("SONEDE", "school", START, END, Decimal("30"))
        second.lower_bound_m3, second.calculation_mode = Decimal("20"), "marginal"
        second.save()
        with self.assertRaises(ValidationError):
            quote_service("SONEDE", "school", START, END, Decimal("30"))

    def test_tariff_change_requires_explicit_period_split(self):
        tariff(valid_until=date(2026, 2, 1))
        tariff(valid_from=date(2026, 2, 2))
        with self.assertRaises(ValidationError):
            quote_service("SONEDE", "school", START, END, Decimal("30"))

    def test_three_decimal_rounding(self):
        tariff(price_per_m3_tnd=Decimal("0.1235"), fixed_fee_tnd=Decimal("0"))
        self.assertEqual(quote_service("SONEDE", "school", START, END, Decimal("1"))[1], Decimal("0.124"))


class BillTests(TestCase):
    def setUp(self):
        self.meter = meter()
        self.first = reading(self.meter, START, 1000)
        self.last = reading(self.meter, END, 1030)
        self.sonede = tariff()
        self.onas = tariff("ONAS", price_per_m3_tnd=Decimal("0.25"), fixed_fee_tnd=Decimal("1"))

    def test_bill_uses_real_index_difference_and_preserves_snapshot(self):
        obj = bill(self.meter)
        self.assertEqual(obj.volume_m3, Decimal("30"))
        self.assertEqual(obj.sonede_amount_tnd, Decimal("25.500"))
        self.assertEqual(obj.onas_amount_tnd, Decimal("8.500"))
        self.assertEqual(obj.total_tnd, Decimal("34.000"))
        self.assertEqual(obj.tariff_snapshot["start_reading"]["id"], self.first.pk)
        self.sonede.price_per_m3_tnd = Decimal("9")
        self.sonede.save()
        obj.refresh_from_db()
        self.assertEqual(obj.tariff_snapshot["SONEDE"]["bands"][0]["price_per_m3_tnd"], "0.7500")

    def test_optional_onas(self):
        obj = bill(self.meter, include_onas=False)
        self.assertIsNone(obj.onas_band)
        self.assertEqual(obj.onas_amount_tnd, Decimal("0"))

    def test_missing_boundary_reading_is_not_interpolated(self):
        with self.assertRaises(ValidationError):
            bill(self.meter, period_end=date(2026, 3, 31))
        self.assertEqual(WaterBill.objects.count(), 0)

    def test_issue_recalculates_then_freezes_and_is_idempotent(self):
        obj = bill(self.meter)
        self.sonede.price_per_m3_tnd = Decimal("1")
        self.sonede.save()
        obj.issue_bill()
        self.assertEqual(obj.total_tnd, Decimal("41.500"))
        timestamp = obj.issued_at
        obj.issue_bill()
        self.assertEqual(obj.issued_at, timestamp)
        obj.total_tnd = Decimal("1")
        with self.assertRaises(ValidationError):
            obj.save()
        with self.assertRaises(ValidationError):
            obj.delete()
        with self.assertRaises(ValidationError):
            WaterBill.objects.filter(pk=obj.pk).delete()

    def test_issued_bill_locks_its_source_readings(self):
        obj = bill(self.meter)
        obj.issue_bill()
        self.first.index_m3 = Decimal("999")
        with self.assertRaises(ValidationError):
            self.first.save()
        with self.assertRaises(ValidationError):
            self.last.delete()
        with self.assertRaises(ValidationError):
            reading(self.meter, date(2026, 2, 1), 1010)

    def test_bill_protects_meter_and_tariff_from_deletion(self):
        bill(self.meter)
        with self.assertRaises(ProtectedError):
            self.meter.delete()
        with self.assertRaises(ProtectedError):
            self.sonede.delete()

    def test_issued_bill_rejects_overlapping_period(self):
        reading(self.meter, date(2026, 2, 1), 1010)
        bill(self.meter).issue_bill()
        with self.assertRaises(ValidationError):
            bill(self.meter, period_start=date(2026, 2, 1), period_end=END)
        # A second identical period is rejected by the unique constraint.
        with self.assertRaises(ValidationError):
            bill(self.meter)
