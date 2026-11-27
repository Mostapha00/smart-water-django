"""
Module quality_leaks — Qualité & fuites (Student 3).

Classes à implémenter (voir le diagramme de classes du dossier de validation) :

- WaterQualityTest : zone (FK infrastructure.WaterZone), sampled_at, laboratory, ph, turbidity_ntu,
                     chlorine_mg_l, conductivity_us_cm, potability_probability, model_version, predicted_at
                     méthodes : classify_potability(), evaluate_rules()
- AlertRule        : name, version_code, parameter, operator, threshold, unit, severity,
                     source_reference, active ; méthode evaluate()
- LeakIncident     : meter (FK consumption.WaterMeter, optionnel), trigger_test (FK WaterQualityTest, optionnel),
                     rule (FK AlertRule, optionnel), technician (FK accounts.NetworkTechnician, optionnel),
                     suspected_pipe (FK infrastructure.WaterPipe), suspected_pump (FK infrastructure.WaterPump),
                     status, description, trigger_evidence (JSON), position_on_pipe (0..1, optionnel),
                     opened_at, resolved_at
                     méthodes : assess_incident(), resolve()
                     ⚠️ au moins UNE source : meter OU trigger_test (ou les deux)
                     ⚠️ au plus UNE cible suspectée (pipe OU pump OU aucune)
                     Le relevé déclencheur n'a pas de FK : ses valeurs sont copiées dans trigger_evidence.

CONTRAT AVEC LA MAQUETTE 3D (infrastructure) — garder ces noms pour que les fuites
s'affichent automatiquement dans la maquette :
  LeakIncident : meter, suspected_pipe, suspected_pump, technician, rule, status,
                 description, opened_at, resolved_at
  Champ optionnel proposé : position_on_pipe (Decimal 0..1, position du point de fuite)
"""
from django.db import models  # noqa: F401
