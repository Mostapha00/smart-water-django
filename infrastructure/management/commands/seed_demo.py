"""
Charge un site de démonstration : École primaire Ennour (La Manouba).

    python manage.py seed_demo            # crée ou met à jour la démo
    python manage.py seed_demo --reset    # supprime la démo puis la recrée

Données FICTIVES, pour le développement et la soutenance.
"""
from datetime import date, datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import NetworkTechnician
from infrastructure.models import MaintenanceWork, Site, WaterPipe, WaterPump, WaterZone

SITE_CODE = "SIT-MNB-001"


def aware(d: date, hour: int = 9):
    return timezone.make_aware(datetime.combine(d, time(hour, 0)))


class Command(BaseCommand):
    help = "Crée le site de démonstration « École primaire Ennour »."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Supprime le site de démo avant de le recréer.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            site = Site.objects.filter(code=SITE_CODE).first()
            if site:
                MaintenanceWork.objects.filter(pipe__zone__site=site).delete()
                MaintenanceWork.objects.filter(pump__zone__site=site).delete()
                WaterPipe.objects.filter(zone__site=site).delete()
                WaterPump.objects.filter(zone__site=site).delete()
                site.delete()
                if opts["verbosity"]:
                    self.stdout.write("Ancienne démo supprimée.")

        tarek, _ = NetworkTechnician.objects.get_or_create(
            staff_id="TEC-001",
            defaults={"name": "Ben Salah", "first_name": "Tarek", "email": "tarek.bensalah@example.tn", "specialty": "Plomberie réseau"},
        )
        sana, _ = NetworkTechnician.objects.get_or_create(
            staff_id="TEC-002",
            defaults={"name": "Jlassi", "first_name": "Sana", "email": "sana.jlassi@example.tn", "specialty": "Pompage"},
        )

        site, _ = Site.objects.update_or_create(
            code=SITE_CODE,
            defaults={"name": "École primaire Ennour", "site_type": Site.SiteType.SCHOOL,
                      "governorate": "La Manouba", "address": "Rue des Jasmins, Den Den"},
        )
        zones = {}
        for code, name, usage, pressure, kind, floors in [
            ("Z-01", "Bloc pédagogique", "Sanitaires", "2.8", "building", 2),
            ("Z-02", "Cantine", "Cuisine", "3.0", "building", 1),
            ("Z-03", "Jardin", "Irrigation", "2.2", "garden", 1),
        ]:
            zones[code], _ = WaterZone.objects.update_or_create(
                site=site, code=code,
                defaults={"name": name, "usage": usage, "service_pressure_bar": Decimal(pressure), "display_kind": kind, "floors": floors},
            )

        pipes = {}
        for ref, zone, inst, status, material, length, diam, main in [
            ("CND-001", "Z-01", date(2015, 9, 1), "en_service", "PEHD", "42", 63, True),
            ("CND-002", "Z-01", date(2015, 9, 1), "en_service", "PVC", "25", 40, False),
            ("CND-003", "Z-02", date(1998, 3, 10), "a_surveiller", "Acier galvanisé", "18", 32, False),
            ("CND-004", "Z-03", date(2009, 4, 22), "en_service", "PEHD", "30", 50, False),
        ]:
            pipes[ref], _ = WaterPipe.objects.update_or_create(
                reference=ref,
                defaults={"zone": zones[zone], "installation_date": inst, "status": status, "material": material,
                          "length_m": Decimal(length), "diameter_mm": diam, "is_main_supply": main},
            )
        pumps = {}
        for ref, zone, inst, status, power, flow, eff in [
            ("PMP-01", "Z-01", date(2018, 1, 15), "en_service", "2.2", "6", "68"),
            ("PMP-02", "Z-03", date(2011, 5, 30), "en_panne", "1.5", "10", "52"),
        ]:
            pumps[ref], _ = WaterPump.objects.update_or_create(
                reference=ref,
                defaults={"zone": zones[zone], "installation_date": inst, "status": status,
                          "power_kw": Decimal(power), "rated_flow_m3_h": Decimal(flow), "efficiency_pct": Decimal(eff)},
            )

        if not MaintenanceWork.objects.filter(pipe__zone__site=site).exists() and not MaintenanceWork.objects.filter(pump__zone__site=site).exists():
            today = timezone.localdate()
            year = today.year
            MaintenanceWork.objects.create(technician=tarek, pump=pumps["PMP-01"], maintenance_type="preventive",
                                           scheduled_at=aware(date(year, 4, 9)), completed_at=aware(date(year, 4, 9), 15),
                                           cost_tnd=Decimal("180"), work_summary="Contrôle annuel, remplacement du joint.")
            MaintenanceWork.objects.create(technician=tarek, pipe=pipes["CND-003"], maintenance_type="corrective",
                                           scheduled_at=aware(date(year, 6, 2)), completed_at=aware(date(year, 6, 3), 12),
                                           cost_tnd=Decimal("420"), work_summary="Reprise d'un raccord corrodé.")
            MaintenanceWork.objects.create(technician=sana, pump=pumps["PMP-02"], maintenance_type="corrective",
                                           scheduled_at=aware(today), work_summary="Le moteur ne démarre plus.")

        for eq in list(pipes.values()) + list(pumps.values()):
            eq.predict_failure_30d()

        if opts["verbosity"]:
            self.stdout.write(self.style.SUCCESS(
                f"Démo prête : {site} — {len(zones)} zones, {len(pipes)} canalisations, {len(pumps)} pompes."
            ))
