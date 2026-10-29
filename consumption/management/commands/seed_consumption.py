"""Create clearly fictional, repeatable data for Student 2's demonstration."""
from datetime import date, timedelta
from decimal import Decimal
import io

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from consumption.models import TariffBand, WaterMeter
from infrastructure.models import Site


class Command(BaseCommand):
    help = "Seed a demo meter, daily readings, and explicitly fictional tariffs."

    def handle(self, *args, **options):
        site = Site.objects.filter(code="SIT-MNB-001").first()
        if site is None:
            call_command("seed_demo", verbosity=0)
            site = Site.objects.get(code="SIT-MNB-001")
        category = "DEMO_NOT_OFFICIAL"
        today = timezone.localdate()
        start = today - timedelta(days=45)
        meter, _ = WaterMeter.objects.get_or_create(serial_number="MTR-DEMO-001", defaults={
            "zone": site.zones.first(), "customer_category": category, "installed_on": date(2020, 1, 1),
        })
        csv = ["recorded_at,index_m3"]
        for offset in range(46):
            day = start + timedelta(days=offset)
            index = Decimal("1000") + Decimal((day - date(2020, 1, 1)).days * 2)
            csv.append(f"{day.isoformat()}T00:00:00+01:00,{index}")
        result = meter.import_csv_readings(io.StringIO("\n".join(csv)))
        for service in TariffBand.Service.values:
            for lower, upper, price in ((Decimal("0"), Decimal("20"), Decimal("0.5")), (Decimal("20"), None, Decimal("1.0"))):
                TariffBand.objects.get_or_create(service=service, customer_category=category,
                    valid_from=date(2020, 1, 1), lower_bound_m3=lower, defaults={
                        "upper_bound_m3": upper, "price_per_m3_tnd": price,
                        "fixed_fee_tnd": Decimal("3"), "reference_period_days": 90,
                        "calculation_mode": TariffBand.Mode.GLOBAL,
                        "official_source": "https://example.invalid/aquamind-demo-tariffs",
                    })
        self.stdout.write(self.style.SUCCESS(f"Demo meter {meter.pk}: {result}. Tariffs are FICTIONAL, not official SONEDE/ONAS rates."))
        self.stdout.write(f"Billing boundary dates: {start} to {today} (end exclusive).")
