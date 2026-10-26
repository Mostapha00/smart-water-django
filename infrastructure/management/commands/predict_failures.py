"""
Recalcule le risque de panne à 30 jours de tous les équipements.

À lancer HORS requête web (tâche planifiée, cron), comme prévu dans l'architecture :
    python manage.py predict_failures
    python manage.py predict_failures --site SIT-MNB-001
"""
from django.core.management.base import BaseCommand

from infrastructure.models import WaterPipe, WaterPump


class Command(BaseCommand):
    help = "Recalcule failure_risk_30d pour les canalisations et les pompes."

    def add_arguments(self, parser):
        parser.add_argument("--site", help="Code du site à traiter (par défaut : tous).")

    def handle(self, *args, **opts):
        count = 0
        for model in (WaterPipe, WaterPump):
            qs = model.objects.prefetch_related("maintenance_works")
            if opts.get("site"):
                qs = qs.filter(zone__site__code=opts["site"])
            for eq in qs:
                risk = eq.predict_failure_30d()
                count += 1
                self.stdout.write(f"{eq.reference:<12} {float(risk) * 100:5.1f} %  ({eq.model_version})")
        self.stdout.write(self.style.SUCCESS(f"{count} équipement(s) recalculé(s)."))
