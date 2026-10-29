import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from consumption.models import WaterMeter
from consumption.services.forecasting import train_meter


class Command(BaseCommand):
    help = "Train an optional LightGBM model from a meter's consecutive daily readings."

    def add_arguments(self, parser):
        parser.add_argument("meter", type=int)

    def handle(self, *args, **options):
        try:
            meter = WaterMeter.objects.get(pk=options["meter"])
            self.stdout.write(json.dumps(train_meter(meter)))
        except WaterMeter.DoesNotExist as exc:
            raise CommandError("Meter not found.") from exc
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
