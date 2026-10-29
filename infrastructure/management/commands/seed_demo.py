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
from consumption.models import MeterReading, TariffBand, WaterBill, WaterMeter
from quality_leaks.models import AlertRule, LeakIncident, WaterQualityTest
from sustainability.models import AuditReport, ConservationTarget, MeasuredBenefit, OptimizationRun, SustainabilityProject
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
                LeakIncident.objects.filter(suspected_pipe__zone__site=site).delete()
                WaterQualityTest.objects.filter(zone__site=site).delete()
                WaterBill.objects.filter(meter__zone__site=site).delete()
                WaterMeter.objects.filter(zone__site=site).delete()
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

        meters = {}
        for serial, zone_code, category in [
            ("MTR-ENNOUR-001", "Z-01", WaterMeter.CustomerCategory.PUBLIC),
            ("MTR-ENNOUR-002", "Z-02", WaterMeter.CustomerCategory.PUBLIC),
            ("MTR-ENNOUR-003", "Z-03", WaterMeter.CustomerCategory.PUBLIC),
        ]:
            meters[serial], _ = WaterMeter.objects.update_or_create(
                serial_number=serial,
                defaults={"zone": zones[zone_code], "customer_category": category, "installed_on": date(2022, 1, 10)},
            )
        base_day = timezone.localdate().replace(day=1)
        for serial, values in {
            "MTR-ENNOUR-001": [("2026-01-01", "120.000"), ("2026-02-01", "148.000"), ("2026-03-01", "179.000")],
            "MTR-ENNOUR-002": [("2026-01-01", "80.000"), ("2026-02-01", "95.000"), ("2026-03-01", "111.000")],
            "MTR-ENNOUR-003": [("2026-01-01", "240.000"), ("2026-02-01", "275.000"), ("2026-03-01", "318.000")],
        }.items():
            meter = meters[serial]
            for recorded, index in values:
                reading, _ = MeterReading.objects.update_or_create(
                    meter=meter, recorded_at=aware(date.fromisoformat(recorded)),
                    defaults={"index_m3": Decimal(index), "source": "demo"},
                )
            meter.forecast_consumption()

        tariff, _ = TariffBand.objects.update_or_create(
            service=TariffBand.Service.SONEDE, customer_category=WaterMeter.CustomerCategory.PUBLIC,
            valid_from=date(2026, 1, 1), lower_bound_m3=Decimal("0"),
            defaults={"upper_bound_m3": None, "price_per_m3_tnd": Decimal("1.250"), "fixed_fee_tnd": Decimal("2.000")},
        )
        bill_meter = meters["MTR-ENNOUR-001"]
        bill, _ = WaterBill.objects.update_or_create(
            meter=bill_meter, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
            defaults={"sonede_band": tariff, "volume_m3": Decimal("28.000")},
        )
        bill.calculate_amounts()

        rule, _ = AlertRule.objects.update_or_create(
            name="Turbidité élevée - démonstration",
            defaults={"version_code": "demo-1", "parameter": "turbidity_ntu", "operator": "gt",
                      "threshold": Decimal("5"), "unit": "NTU", "severity": "critical",
                      "source_reference": "Référence démonstration", "active": True},
        )
        quality_test, _ = WaterQualityTest.objects.update_or_create(
            zone=zones["Z-02"], sampled_at=aware(date(2026, 3, 10)),
            defaults={"laboratory": "Laboratoire municipal", "ph": Decimal("7.2"),
                      "turbidity_ntu": Decimal("8.5"), "chlorine_mg_l": Decimal("0.3"),
                      "conductivity_us_cm": Decimal("620")},
        )
        quality_test.classify_potability()
        incident, _ = LeakIncident.objects.update_or_create(
            reference="FUI-ENNOUR-001",
            defaults={"meter": meters["MTR-ENNOUR-002"], "trigger_test": quality_test, "rule": rule,
                      "technician": tarek, "suspected_pipe": pipes["CND-003"],
                      "status": "investigation", "description": "Baisse de qualité et suspicion sur le raccord de la cantine.",
                      "trigger_evidence": {"turbidity_ntu": "8.5", "threshold": "5"}},
        )
        incident.assess_incident()

        ConservationTarget.objects.update_or_create(
            site=site,
            name="Réduction annuelle de l'école",
            defaults={
                "period_start": date(2026, 1, 1),
                "period_end": date(2026, 12, 31),
                "baseline_m3": Decimal("1200"),
                "target_reduction_percent": Decimal("15"),
                "department": "Direction de l'école",
                "notes": "Objectif de démonstration basé sur les relevés des compteurs.",
            },
        )
        project, _ = SustainabilityProject.objects.update_or_create(
            site=site,
            name="Réparation du raccord cantine",
            defaults={
                "project_type": SustainabilityProject.ProjectType.RETROFIT,
                "description": "Remplacement du raccord identifié lors de l'analyse de fuite.",
                "budget_tnd": Decimal("850"),
                "expected_savings_m3": Decimal("180"),
                "expected_annual_savings_tnd": Decimal("225"),
                "status": SustainabilityProject.Status.APPROVED,
                "start_date": date(2026, 4, 1),
            },
        )
        MeasuredBenefit.objects.update_or_create(
            project=project,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 6, 30),
            defaults={
                "measured_savings_m3": Decimal("42"),
                "measured_savings_tnd": Decimal("52.5"),
                "verified": True,
                "evidence": "Comparaison des index avant/après intervention.",
            },
        )
        OptimizationRun.objects.update_or_create(
            site=site,
            budget_tnd=Decimal("1000"),
            defaults={
                "objective": "water_savings",
                "solver": "demo",
                "recommendations": [{"id": project.pk, "name": project.name, "cost_tnd": "850", "savings_m3": "180"}],
                "total_cost_tnd": Decimal("850"),
                "projected_savings_m3": Decimal("180"),
                "projected_annual_savings_tnd": Decimal("225"),
                "payback_months": Decimal("45.3"),
            },
        )
        AuditReport.objects.update_or_create(
            site=site,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            defaults={
                "snapshot": {"consumption_m3": "180", "active_leaks": 1, "quality_score": "0.75"},
            },
        )

        if opts["verbosity"]:
            self.stdout.write(self.style.SUCCESS(
                f"Démo prête : {site} — {len(zones)} zones, {len(pipes)} canalisations, {len(pumps)} pompes."
            ))
