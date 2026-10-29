from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from consumption.models import WaterMeter


class Command(BaseCommand):
    help = "Forecast active meters and persist their results."

    def add_arguments(self, parser):
        parser.add_argument("--meter", type=int)
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **options):
        meters = WaterMeter.objects.filter(pk=options["meter"]) if options["meter"] else WaterMeter.objects.filter(active=True)
        if options["meter"] and not meters.exists():
            raise CommandError("Meter not found.")
        failed = 0
        for meter in meters:
            try:
                result = meter.forecast_consumption(options["days"])
                self.stdout.write(f"{meter}: {result['forecast_m3']} m³ / {result['model_version']}")
            except ValidationError as exc:
                failed += 1
                self.stderr.write(f"{meter}: {' '.join(exc.messages)}")
        if failed:
            raise CommandError(f"{failed} meter(s) could not be forecast.")
