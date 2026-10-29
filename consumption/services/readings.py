"""Validated, bounded, idempotent CSV imports without partial writes."""
import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from consumption.models import MeterReading, WaterMeter, invalidate_forecast

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000


def parse_rows(file):
    content = file.read(MAX_BYTES + 1)
    if isinstance(content, str):
        content = content.encode("utf-8")
    if len(content) > MAX_BYTES:
        raise ValidationError("CSV files must be no larger than 2 MiB.")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != ["recorded_at", "index_m3"]:
            raise ValidationError("CSV header must be exactly: recorded_at,index_m3")
        rows = {}
        for number, row in enumerate(reader, 2):
            if number > MAX_ROWS + 1:
                raise ValidationError("CSV files are limited to 10,000 rows.")
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError
                stamp = parse_datetime(row["recorded_at"].strip())
                if stamp is None:
                    raise ValueError
                if timezone.is_naive(stamp):
                    stamp = timezone.make_aware(stamp)
                index = Decimal(row["index_m3"].strip())
                field = MeterReading._meta.get_field("index_m3")
                index = field.clean(index, None)
                if stamp in rows and rows[stamp] != index:
                    raise ValueError("conflicting duplicate")
                rows[stamp] = index
            except (ValueError, InvalidOperation, ValidationError) as exc:
                raise ValidationError(f"Invalid CSV row {number}: use an ISO timestamp and a nonnegative cumulative index with at most 3 decimal places.") from exc
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValidationError("The file must be valid UTF-8 CSV.") from exc
    if not rows:
        raise ValidationError("The CSV contains no readings.")
    return rows


@transaction.atomic
def import_readings(meter, file):
    rows = parse_rows(file)
    meter = WaterMeter.objects.select_for_update().get(pk=meter.pk)
    existing = dict(meter.readings.values_list("recorded_at", "index_m3"))
    new = []
    for stamp, index in rows.items():
        if stamp in existing:
            if existing[stamp] != index:
                raise ValidationError("The CSV conflicts with an existing index at the same timestamp.")
            continue
        reading = MeterReading(meter=meter, recorded_at=stamp, index_m3=index, source=MeterReading.Source.CSV)
        if timezone.localdate(stamp) < meter.installed_on:
            raise ValidationError("A reading cannot predate meter installation.")
        reading._check_issued_bills()
        new.append(reading)
    combined = existing | rows
    ordered = sorted(combined.items())
    if any(right[1] < left[1] for left, right in zip(ordered, ordered[1:])):
        raise ValidationError("Cumulative indexes must not decrease over time; nothing was imported.")
    MeterReading.objects.bulk_create(new)
    if new:
        invalidate_forecast(meter.pk)
    return {"created": len(new), "skipped": len(rows) - len(new)}
