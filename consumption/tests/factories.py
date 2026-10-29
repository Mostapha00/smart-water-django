from datetime import date
from decimal import Decimal

from infrastructure.tests.factories import make_site, make_zone
from consumption.models import MeterReading, TariffBand, WaterBill, WaterMeter, midnight


def meter(**kwargs):
    defaults = dict(zone=make_zone(make_site()), serial_number="M-001", customer_category="school", installed_on=date(2025, 1, 1))
    defaults.update(kwargs)
    return WaterMeter.objects.create(**defaults)


def reading(m, day, index):
    return MeterReading.objects.create(meter=m, recorded_at=midnight(day), index_m3=Decimal(str(index)))


def tariff(service="SONEDE", **kwargs):
    defaults = dict(service=service, customer_category="school", valid_from=date(2026, 1, 1),
                    lower_bound_m3=Decimal("0"), upper_bound_m3=None, price_per_m3_tnd=Decimal("0.7500"),
                    fixed_fee_tnd=Decimal("3.000"), reference_period_days=90,
                    official_source="https://example.invalid/demo-not-official")
    defaults.update(kwargs)
    return TariffBand.objects.create(**defaults)


def bill(m, **kwargs):
    defaults = dict(meter=m, period_start=date(2026, 1, 1), period_end=date(2026, 4, 1), include_onas=True)
    defaults.update(kwargs)
    obj = WaterBill(**defaults)
    obj.calculate_amounts()
    return obj
