"""Configurable educational estimates, with no hard-coded official rates."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from consumption.models import TariffBand, WaterBill, WaterMeter

MILLI = Decimal("0.001")


def money(value):
    return value.quantize(MILLI, rounding=ROUND_HALF_UP)


def quote_service(service, category, start, end, volume):
    """Quote [start, end); validity dates are inclusive, volume bands half-open.

    Bounds and the fixed fee are prorated by actual days/reference_period_days.
    A tariff change inside the period must be split explicitly by the caller.
    Taxes and category-specific ONAS exceptions are not guessed by this engine.
    """
    if end <= start or volume < 0:
        raise ValidationError("A positive period and nonnegative volume are required.")
    days = (end - start).days
    last_day = end - timedelta(days=1)
    bands = list(TariffBand.objects.filter(
        service=service, customer_category=category, valid_from__lte=start,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=last_day)).order_by("lower_bound_m3"))
    if not bands:
        raise ValidationError(f"No {service} tariff covers the whole period. Configure tariffs or split the period at a tariff change.")
    first = bands[0]
    common = (first.calculation_mode, first.reference_period_days, first.fixed_fee_tnd, first.valid_from, first.valid_until)
    cursor = Decimal("0")
    for band in bands:
        if (band.calculation_mode, band.reference_period_days, band.fixed_fee_tnd, band.valid_from, band.valid_until) != common:
            raise ValidationError(f"{service} bands must share the same mode, duration, fixed fee, and validity dates.")
        if cursor is None or band.lower_bound_m3 != cursor:
            raise ValidationError(f"{service} bands contain a gap or overlap; they must start at zero.")
        cursor = band.upper_bound_m3
    factor = Decimal(days) / first.reference_period_days
    normalized_volume = volume / factor
    if first.calculation_mode == TariffBand.Mode.GLOBAL:
        reached = next((b for b in bands if b.lower_bound_m3 <= normalized_volume and (b.upper_bound_m3 is None or normalized_volume < b.upper_bound_m3)), None)
        if reached is None:
            raise ValidationError(f"{service} bands do not cover this consumption.")
        used = [reached]
    else:
        if cursor is not None and normalized_volume > cursor:
            raise ValidationError(f"{service} bands do not cover this consumption.")
        used = [b for b in bands if b.lower_bound_m3 < normalized_volume] or [first]
        reached = used[-1]
    variable = sum((b.calculate_variable_charge(volume, days) for b in used), Decimal("0"))
    fixed = first.fixed_fee_tnd * factor  # Once per service, never once per band.
    snapshot = {
        "service": service, "customer_category": category,
        "period_start": start.isoformat(), "period_end_exclusive": end.isoformat(),
        "days": days, "reference_period_days": first.reference_period_days,
        "calculation_mode": first.calculation_mode, "volume_m3": str(volume),
        "variable_tnd": str(money(variable)), "fixed_tnd": str(money(fixed)),
        "amount_tnd": str(money(variable + fixed)), "taxes_included": False,
        "bands": [{
            "id": b.pk, "lower_bound_m3": str(b.lower_bound_m3),
            "upper_bound_m3": str(b.upper_bound_m3) if b.upper_bound_m3 is not None else None,
            "price_per_m3_tnd": str(b.price_per_m3_tnd), "fixed_fee_tnd": str(b.fixed_fee_tnd),
            "valid_from": b.valid_from.isoformat(),
            "valid_until": b.valid_until.isoformat() if b.valid_until else None,
            "official_source": b.official_source,
        } for b in used],
    }
    return reached, money(variable + fixed), snapshot


def _calculate(bill):
    volume, first, last = bill.meter.volume_between(bill.period_start, bill.period_end)
    bill.volume_m3 = volume
    bill.sonede_band, bill.sonede_amount_tnd, sonede = quote_service(
        TariffBand.Service.SONEDE, bill.meter.customer_category, bill.period_start, bill.period_end, volume,
    )
    bill.onas_band, bill.onas_amount_tnd, onas = None, Decimal("0.000"), None
    if bill.include_onas:
        bill.onas_band, bill.onas_amount_tnd, onas = quote_service(
            TariffBand.Service.ONAS, bill.meter.customer_category, bill.period_start, bill.period_end, volume,
        )
    bill.total_tnd = bill.sonede_amount_tnd + bill.onas_amount_tnd
    bill.tariff_snapshot = {
        "schema_version": 1, "currency": "TND", "estimate_excluding_taxes": True,
        "meter": bill.meter_id, "customer_category": bill.meter.customer_category,
        "start_reading": {"id": first.pk, "recorded_at": first.recorded_at.isoformat(), "index_m3": str(first.index_m3)},
        "end_reading": {"id": last.pk, "recorded_at": last.recorded_at.isoformat(), "index_m3": str(last.index_m3)},
        "SONEDE": sonede, "ONAS": onas,
    }


@transaction.atomic
def recalculate_bill(bill):
    WaterMeter.objects.select_for_update().get(pk=bill.meter_id)
    if bill.pk:
        stored = WaterBill.objects.select_for_update().get(pk=bill.pk)
        if stored.issued_at:
            raise ValidationError("An issued bill cannot be recalculated.")
    _calculate(bill)
    bill.save()
    return bill.total_tnd


@transaction.atomic
def issue_bill(bill):
    WaterMeter.objects.select_for_update().get(pk=bill.meter_id)
    stored = WaterBill.objects.select_for_update().get(pk=bill.pk)
    if stored.issued_at:
        bill.refresh_from_db()
        return bill
    _calculate(stored)
    stored.issued_at = timezone.now()
    stored.save()
    bill.refresh_from_db()
    return bill
