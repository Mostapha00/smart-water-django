from datetime import date
from decimal import Decimal

from accounts.models import NetworkTechnician
from infrastructure.models import Site, WaterPipe, WaterPump, WaterZone


def make_site(code="SIT-T-001", **kw):
    defaults = {"name": "Site test", "site_type": "ecole", "governorate": "Tunis"}
    defaults.update(kw)
    return Site.objects.create(code=code, **defaults)


def make_zone(site, code="Z-01", **kw):
    defaults = {"name": "Zone test", "usage": "Sanitaires", "service_pressure_bar": Decimal("2.5")}
    defaults.update(kw)
    return WaterZone.objects.create(site=site, code=code, **defaults)


def make_pipe(zone, reference="CND-T1", **kw):
    defaults = {"material": "PEHD", "length_m": Decimal("10"), "diameter_mm": 50, "installation_date": date(2010, 1, 1)}
    defaults.update(kw)
    return WaterPipe.objects.create(zone=zone, reference=reference, **defaults)


def make_pump(zone, reference="PMP-T1", **kw):
    defaults = {"power_kw": Decimal("2"), "rated_flow_m3_h": Decimal("5"), "installation_date": date(2015, 1, 1)}
    defaults.update(kw)
    return WaterPump.objects.create(zone=zone, reference=reference, **defaults)


def make_tech(staff_id="TEC-T1"):
    return NetworkTechnician.objects.create(staff_id=staff_id, name="Test", first_name="Tech", email=f"{staff_id}@example.tn")
