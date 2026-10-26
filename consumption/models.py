"""
Module consumption — Consommation & facturation (Student 2).

Classes à implémenter (voir le diagramme de classes du dossier de validation) :

- WaterMeter      : zone (FK infrastructure.WaterZone), serial_number, customer_category,
                    installed_on, active, forecast_m3, horizon_days, model_version, predicted_at
                    méthodes : forecast_consumption(), import_csv_readings()
- MeterReading    : meter (FK WaterMeter), recorded_at, index_m3 (index CUMULÉ), source,
                    anomaly_score, model_version, analyzed_at
                    méthodes : calculate_volume(), detect_anomaly()
- TariffBand      : service (SONEDE / ONAS), customer_category, valid_from, valid_until,
                    lower_bound_m3, upper_bound_m3, price_per_m3_tnd, fixed_fee_tnd, ...
- WaterBill       : meter, sonede_band, onas_band, période, montants, tariff_snapshot (JSON)

CONTRAT AVEC LA MAQUETTE 3D (infrastructure) — garder ces noms pour que les compteurs
s'affichent automatiquement dans la maquette :
  WaterMeter : zone, serial_number, customer_category, forecast_m3, horizon_days
  MeterReading : meter (related_name="readings"), recorded_at, index_m3
"""
from django.db import models  # noqa: F401
