"""
Charge le site « Technopole El Ghazala — secteur TEK-UP » (Raoued, Ariana).

    python manage.py seed_tekup            # crée ou met à jour le site
    python manage.py seed_tekup --reset    # supprime le site puis le recrée

Emplacement et voisinage des bâtiments : OpenStreetMap (TEK-UP, ESPRIT, Sup'Com,
cité universitaire, Pépinière / E1-E3, ST, Tunisie Télécom, Olympico, bureaux de
Chotrana II). Toutes les données hydrauliques sont des ESTIMATIONS faites pour la
démonstration, pas des données SONEDE réelles :

- consommation : effectif estimé × dotation (≈ 20 L/étudiant/jour ouvré,
  ≈ 15 L/employé/jour, ≈ 120 L/résident/jour en foyer) + climatisation pour les
  bâtiments techniques + arrosage (≈ 5 mm/jour l'été) pour les terrains ;
- profil saisonnier : vacances universitaires en juillet-août, pic de
  climatisation et d'arrosage l'été ;
- canalisations : longueurs mesurées à vol d'oiseau sur la carte depuis la
  conduite principale de la technopole, diamètres et matières choisis selon la
  taille du bâtiment et son année de construction (technopole ouverte vers 2000).
"""
import random
from datetime import date, datetime, time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import NetworkTechnician
from consumption.models import MeterReading, WaterMeter
from infrastructure.models import MaintenanceWork, Site, WaterPipe, WaterPump, WaterZone
from quality_leaks.models import LeakIncident, WaterQualityTest
from sustainability.models import ConservationTarget, SustainabilityProject

SITE_CODE = "SIT-ARI-GHZ-01"
P = "GHZ"  # préfixe des références (uniques dans toute la base)

# Profils saisonniers, coefficient par mois de janvier à octobre
PROFILES = {
    "univ":   [1.00, 1.00, 1.00, 0.85, 1.00, 0.80, 0.25, 0.20, 0.90, 1.00],
    "office": [0.90, 0.90, 0.95, 1.00, 1.05, 1.15, 1.20, 1.10, 1.05, 1.00],
    "dorm":   [1.00, 1.00, 1.00, 0.90, 1.00, 0.85, 0.30, 0.25, 0.80, 1.00],
    "cool":   [0.90, 0.90, 0.95, 1.00, 1.10, 1.25, 1.40, 1.40, 1.20, 1.00],
    "garden": [0.30, 0.30, 0.50, 0.80, 1.20, 1.60, 1.90, 1.90, 1.30, 0.70],
}

# code, nom, usage, pression (bar), forme 3D, étages, pos_x, pos_y, catégorie, m³/mois de base, profil
# Rangée du fond (pos_y = -9) = nord de la carte ; rangée de devant (-1.5) = sud, côté branchement SONEDE.
ZONES = [
    ("Z-01", "TEK-UP", "Salles, labos, sanitaires, cafétéria", "3.2", "building", 5, 9, -9, "commercial", 650, "univ"),
    ("Z-02", "ESPRIT — campus El Ghazala", "Salles, sanitaires, restauration", "3.2", "building", 5, 0, -9, "commercial", 1800, "univ"),
    ("Z-03", "Bureaux Chotrana II (Wevioo, Picosoft, ARDIA…)", "Bureaux, sanitaires, climatisation", "3.5", "building", 5, 29, -9, "commercial", 520, "office"),
    ("Z-04", "Écoles privées Chotrana II est", "Salles, sanitaires", "3.0", "building", 3, 50, -9, "commercial", 380, "univ"),
    ("Z-05", "Sup'Com — blocs pédagogiques", "Salles, labos, sanitaires", "2.8", "building", 2, -50, -1.5, "public", 700, "univ"),
    ("Z-06", "Cité universitaire (foyers, restaurant U)", "Douches, cuisine collective", "2.6", "building", 2, -40, -1.5, "public", 2100, "dorm"),
    ("Z-07", "Pépinière & immeubles E1–E3", "Bureaux, sanitaires", "3.4", "building", 5, -26, -1.5, "commercial", 300, "office"),
    ("Z-08", "ST Tunisia", "Bureaux, sanitaires, climatisation", "3.0", "building", 2, -16, -1.5, "industrial", 480, "office"),
    ("Z-09", "Tunisie Télécom — Pôle TIC", "Bureaux, refroidissement salles techniques", "3.0", "building", 3, 18, -1.5, "commercial", 360, "cool"),
    ("Z-10", "Olympico Club — terrains", "Arrosage des terrains, vestiaires", "2.4", "garden", 1, 40, -1.5, "commercial", 900, "garden"),
]

# référence, zone, installation, statut, matière, longueur (m), diamètre (mm), conduite principale
PIPES = [
    ("CND-00", "Z-02", date(2001, 6, 1), "en_service", "Fonte", "380", 200, True),
    ("CND-01", "Z-01", date(2014, 9, 1), "en_service", "PEHD", "210", 90, False),
    ("CND-02", "Z-01", date(2014, 9, 1), "en_service", "PVC", "85", 50, False),
    ("CND-03", "Z-02", date(2012, 9, 1), "en_service", "PEHD", "240", 110, False),
    ("CND-04", "Z-03", date(2016, 3, 15), "en_service", "PEHD", "180", 90, False),
    ("CND-05", "Z-04", date(2018, 9, 1), "en_service", "PEHD", "260", 75, False),
    ("CND-06", "Z-05", date(2001, 6, 1), "a_surveiller", "Fonte", "320", 110, False),
    ("CND-07", "Z-06", date(2001, 6, 1), "a_surveiller", "Acier galvanisé", "290", 90, False),
    ("CND-08", "Z-06", date(2008, 10, 1), "en_service", "PVC", "120", 63, False),
    ("CND-09", "Z-07", date(2003, 1, 20), "en_service", "PVC", "140", 75, False),
    ("CND-10", "Z-08", date(2005, 5, 10), "en_service", "PEHD", "150", 110, False),
    ("CND-11", "Z-09", date(2004, 2, 1), "en_service", "PEHD", "190", 90, False),
    ("CND-12", "Z-10", date(2015, 4, 1), "en_service", "PEHD", "230", 63, False),
]

# référence, zone, installation, statut, puissance (kW), débit (m³/h), rendement (%)
PUMPS = [
    ("PMP-01", "Z-01", date(2014, 9, 1), "en_service", "5.5", "18", "72"),
    ("PMP-02", "Z-02", date(2012, 9, 1), "en_service", "7.5", "25", "70"),
    ("PMP-03", "Z-03", date(2016, 3, 15), "en_service", "5.5", "15", "74"),
    ("PMP-04", "Z-05", date(2001, 6, 1), "a_surveiller", "3", "10", "50"),
    ("PMP-05", "Z-06", date(2008, 10, 1), "en_panne", "4", "12", "58"),
    ("PMP-06", "Z-07", date(2003, 1, 20), "a_surveiller", "4", "10", "55"),
    ("PMP-07", "Z-10", date(2015, 4, 1), "en_service", "7.5", "30", "65"),
]


def aware(d: date, hour: int = 9):
    return timezone.make_aware(datetime.combine(d, time(hour, 0)))


def ref(code: str) -> str:
    return f"{P}-{code}"


class Command(BaseCommand):
    help = "Crée le site « Technopole El Ghazala — secteur TEK-UP » avec une infrastructure estimée."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Supprime le site avant de le recréer.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            self._delete()

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
            defaults={"name": "Technopole El Ghazala — secteur TEK-UP", "site_type": Site.SiteType.OTHER,
                      "governorate": "Ariana",
                      "address": "Rue de Newton, Technopole El Ghazala / Chotrana II, 2088 Raoued"},
        )

        zones, meta = {}, {}
        for code, name, usage, pressure, kind, floors, x, y, category, base, profile in ZONES:
            zones[code], _ = WaterZone.objects.update_or_create(
                site=site, code=code,
                defaults={"name": name, "usage": usage, "service_pressure_bar": Decimal(pressure),
                          "display_kind": kind, "floors": floors,
                          "pos_x": Decimal(str(x)), "pos_y": Decimal(str(y))},
            )
            meta[code] = (category, base, profile)

        pipes = {}
        for code, zone, inst, status, material, length, diam, main in PIPES:
            pipes[code], _ = WaterPipe.objects.update_or_create(
                reference=ref(code),
                defaults={"zone": zones[zone], "installation_date": inst, "status": status, "material": material,
                          "length_m": Decimal(length), "diameter_mm": diam, "is_main_supply": main},
            )
        pumps = {}
        for code, zone, inst, status, power, flow, eff in PUMPS:
            pumps[code], _ = WaterPump.objects.update_or_create(
                reference=ref(code),
                defaults={"zone": zones[zone], "installation_date": inst, "status": status,
                          "power_kw": Decimal(power), "rated_flow_m3_h": Decimal(flow), "efficiency_pct": Decimal(eff)},
            )

        if not (MaintenanceWork.objects.filter(pipe__zone__site=site).exists()
                or MaintenanceWork.objects.filter(pump__zone__site=site).exists()):
            today = timezone.localdate()
            MaintenanceWork.objects.create(
                technician=sana, pump=pumps["PMP-01"], maintenance_type="preventive",
                scheduled_at=aware(date(2026, 3, 12)), completed_at=aware(date(2026, 3, 12), 14),
                cost_tnd=Decimal("350"), work_summary="Révision du surpresseur TEK-UP, contrôle du ballon.")
            MaintenanceWork.objects.create(
                technician=tarek, pipe=pipes["CND-06"], maintenance_type="corrective",
                scheduled_at=aware(date(2026, 5, 20)), completed_at=aware(date(2026, 5, 21), 16),
                cost_tnd=Decimal("1250"), work_summary="Remplacement d'un manchon fissuré sur la conduite Sup'Com.")
            MaintenanceWork.objects.create(
                technician=sana, pump=pumps["PMP-05"], maintenance_type="corrective",
                scheduled_at=aware(today), work_summary="Surpresseur des foyers à l'arrêt : douches sans pression aux étages.")

        for eq in list(pipes.values()) + list(pumps.values()):
            eq.predict_failure_30d()

        # Compteurs + relevés mensuels estimés (index au 1er de chaque mois, janvier → novembre 2026)
        rng = random.Random(2088)
        meters = {}
        for code, zone in zones.items():
            category, base, profile = meta[code]
            meter, _ = WaterMeter.objects.update_or_create(
                serial_number=f"MTR-{P}-{code[2:]}",
                defaults={"zone": zone, "customer_category": category, "installed_on": date(2020, 1, 15)},
            )
            meters[code] = meter
            index = Decimal(rng.randint(8000, 60000))
            months = [date(2026, m, 1) for m in range(1, 12)]
            MeterReading.objects.update_or_create(
                meter=meter, recorded_at=aware(months[0]), defaults={"index_m3": index, "source": "estimation"})
            for i, coef in enumerate(PROFILES[profile]):
                volume = base * coef * rng.uniform(0.94, 1.06)
                if code == "Z-06" and i == 9:  # octobre : fuite simulée sur la conduite acier de la cité U
                    volume *= 1.35
                index += Decimal(str(round(volume, 3)))
                MeterReading.objects.update_or_create(
                    meter=meter, recorded_at=aware(months[i + 1]), defaults={"index_m3": index, "source": "estimation"})
            meter.forecast_consumption()

        quality, _ = WaterQualityTest.objects.update_or_create(
            zone=zones["Z-06"], sampled_at=aware(date(2026, 10, 22)),
            defaults={"laboratory": "Laboratoire SONEDE (estimation)", "ph": Decimal("7.4"),
                      "turbidity_ntu": Decimal("3.8"), "chlorine_mg_l": Decimal("0.18"),
                      "conductivity_us_cm": Decimal("1150")},
        )
        quality.classify_potability()
        WaterQualityTest.objects.update_or_create(
            zone=zones["Z-01"], sampled_at=aware(date(2026, 10, 15)),
            defaults={"laboratory": "Laboratoire SONEDE (estimation)", "ph": Decimal("7.6"),
                      "turbidity_ntu": Decimal("0.6"), "chlorine_mg_l": Decimal("0.45"),
                      "conductivity_us_cm": Decimal("980")},
        )[0].classify_potability()

        incident, _ = LeakIncident.objects.update_or_create(
            reference=f"FUI-{P}-001",
            defaults={"meter": meters["Z-06"], "trigger_test": quality, "technician": tarek,
                      "suspected_pipe": pipes["CND-07"], "status": "investigation", "position_on_pipe": Decimal("0.62"),
                      "description": "Consommation d'octobre des foyers +35 % au-dessus du profil attendu ; "
                                     "chlore résiduel bas. Conduite acier galvanisé de 2001 suspectée.",
                      "trigger_evidence": {"source": "estimation", "excess_volume_pct": 35}},
        )
        incident.assess_incident()

        ConservationTarget.objects.update_or_create(
            site=site, name="Réduction 2026 — secteur TEK-UP",
            defaults={"period_start": date(2026, 1, 1), "period_end": date(2026, 12, 31),
                      "baseline_m3": Decimal("90000"), "target_reduction_percent": Decimal("10"),
                      "department": "Gestion technique de la technopole",
                      "notes": "Base estimée à partir des volumes simulés des 10 zones."},
        )
        SustainabilityProject.objects.update_or_create(
            site=site, name="Remplacement de la conduite acier de la cité U",
            defaults={"project_type": SustainabilityProject.ProjectType.RETROFIT,
                      "description": "Remplacer CND-07 (acier galvanisé, 2001) par du PEHD DN90.",
                      "budget_tnd": Decimal("21500"), "expected_savings_m3": Decimal("6500"),
                      "expected_annual_savings_tnd": Decimal("8100"),
                      "status": SustainabilityProject.Status.APPROVED, "start_date": date(2026, 12, 1)},
        )

        if opts["verbosity"]:
            self.stdout.write(self.style.SUCCESS(
                f"Site prêt : {site} — {len(zones)} zones, {len(pipes)} canalisations, {len(pumps)} pompes, "
                f"{len(meters)} compteurs (données estimées)."
            ))

    def _delete(self):
        site = Site.objects.filter(code=SITE_CODE).first()
        if not site:
            return
        LeakIncident.objects.filter(reference__startswith=f"FUI-{P}-").delete()
        WaterQualityTest.objects.filter(zone__site=site).delete()
        MeterReading.objects.filter(meter__zone__site=site).delete()
        WaterMeter.objects.filter(zone__site=site).delete()
        MaintenanceWork.objects.filter(pipe__zone__site=site).delete()
        MaintenanceWork.objects.filter(pump__zone__site=site).delete()
        WaterPipe.objects.filter(zone__site=site).delete()
        WaterPump.objects.filter(zone__site=site).delete()
        site.delete()
        self.stdout.write("Ancien site supprimé.")
