"""
Entraîne les modèles d'IA puis recalcule toutes les prédictions. À lancer HORS requête web
(après seed_demo / seed_tekup, puis régulièrement, par exemple chaque nuit) :

    python manage.py train_models
    python manage.py train_models --predict-only   # recalcule sans réentraîner

1. Random Forest  : risque de panne à 30 jours (infrastructure)
2. LightGBM       : prévision de consommation (consumption)
3. Isolation Forest : consommations anormales / fuites possibles (consumption, ajusté à chaque analyse)
Les modèles sont enregistrés dans settings.AQUAMIND_ML_DIR (media/ml/, non versionné).
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from consumption.models import WaterMeter
from consumption.services.anomaly import analyze
from consumption.services.forecasting import train_consumption_model
from infrastructure.models import WaterPipe, WaterPump
from infrastructure.services.risk_training import RELIABLE_POSITIVES, train_failure_model


class Command(BaseCommand):
    help = "Entraîne le Random Forest et LightGBM, puis recalcule risques, prévisions et anomalies."

    def add_arguments(self, parser):
        parser.add_argument("--predict-only", action="store_true", help="Recalcule les prédictions sans réentraîner.")

    def handle(self, *args, **opts):
        if not opts["predict_only"]:
            self._train("Random Forest (risque de panne)", train_failure_model, self._describe_failure)
            self._train("LightGBM (prévision de consommation)", train_consumption_model, self._describe_forecast)

        versions = {}
        for eq in list(WaterPipe.objects.prefetch_related("maintenance_works")) + list(WaterPump.objects.prefetch_related("maintenance_works")):
            eq.predict_failure_30d()
            versions[eq.model_version] = versions.get(eq.model_version, 0) + 1
        self.stdout.write(f"Risque de panne recalculé : {self._fmt(versions)}")

        versions = {}
        for meter in WaterMeter.objects.prefetch_related("readings"):
            if meter.forecast_consumption() is not None:
                versions[meter.model_version] = versions.get(meter.model_version, 0) + 1
        self.stdout.write(f"Prévisions recalculées : {self._fmt(versions) or 'aucun compteur avec 2 relevés'}")

        result = analyze()
        self.stdout.write(f"Anomalies ({result['version']}) : {result['anomalies']} relevé(s) signalé(s) sur {result['analyzed']}, "
                          f"{result['incidents_opened']} incident(s) de fuite ouvert(s)")
        self.stdout.write(self.style.SUCCESS("Terminé."))

    def _train(self, label, train, describe):
        try:
            result = train()
        except ValidationError as exc:
            self.stdout.write(self.style.WARNING(f"{label} : non entraîné. {' '.join(exc.messages)} La règle simple reste utilisée."))
            return
        self.stdout.write(self.style.SUCCESS(f"{label} : {result['version']}"))
        for line in describe(result):
            self.stdout.write(f"  {line}")

    def _describe_failure(self, r):
        yield f"{r['samples']} périodes d'apprentissage, dont {r['positives']} suivie(s) d'une panne."
        top = sorted(r["feature_importance"].items(), key=lambda kv: kv[1], reverse=True)
        yield "Variables les plus utiles : " + ", ".join(f"{k} ({v:.0%})" for k, v in top[:3])
        if r["demo"]:
            yield self.style.WARNING(f"Modèle de DÉMONSTRATION : moins de {RELIABLE_POSITIVES} pannes enregistrées, "
                                     "ses prédictions ne sont pas fiables.")

    def _describe_forecast(self, r):
        yield f"{r['train_periods']} périodes d'apprentissage, {r['test_periods']} périodes de test (dernier mois de chaque compteur)."
        if "mae_m3_per_day" in r:
            model, rule = r["mae_m3_per_day"], r["baseline_mae_m3_per_day"]
            verdict = "meilleur que" if model < rule else "PAS meilleur que"
            style = self.style.SUCCESS if model < rule else self.style.WARNING
            yield style(f"Erreur moyenne : LightGBM {model} m³/jour, moyenne simple {rule} m³/jour -> le modèle est {verdict} la règle.")

    @staticmethod
    def _fmt(counter):
        return ", ".join(f"{n} × {v}" for v, n in sorted(counter.items()))
