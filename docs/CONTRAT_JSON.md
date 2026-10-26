# Contrat de données de la maquette 3D

La vue `infrastructure:site_maquette_json` (`/infrastructure/sites/<id>/maquette.json`) renvoie un objet JSON par site. Le fichier `infrastructure/services/maquette.py` le construit ; `infrastructure/static/infrastructure/maquette.js` le lit.

Toute modification de ce format se décide en équipe et se reporte ici.

## Clés

| Clé | Contenu | Source |
| --- | --- | --- |
| `site` | `id`, `code`, `name`, `site_type`, `governorate`, `address` | `Site` |
| `today` | date du jour (`AAAA-MM-JJ`) | serveur |
| `can_edit` | l'utilisateur peut déplacer les zones | permission `change_waterzone` |
| `urls` | modèles d'URL avec `__id__` à remplacer | `infrastructure/urls.py` |
| `technicians` | `id`, `name` | `NetworkTechnician` |
| `zones` | `id`, `code`, `name`, `usage`, `service_pressure_bar`, `kind` (`building` / `garden`), `floors`, `roof`, `pos_x`, `pos_y` | `WaterZone` |
| `equipment` | `id`, `type` (`pipe` / `pump`), `reference`, `zone`, `installation_date`, `status`, `failure_risk_30d`, `model_version`, `replacement_cost_tnd`, `history` ; canalisation : `role` (`main` / `branch`), `material`, `length_m`, `diameter_mm` ; pompe : `power_kw`, `rated_flow_m3_h`, `efficiency_pct` | `WaterPipe`, `WaterPump` |
| `works` | `id`, `reference`, `pipe`, `pump` (références, une seule renseignée), `technician`, `maintenance_type`, `scheduled_at`, `completed_at`, `cost_tnd`, `work_summary` | `MaintenanceWork` |
| `meters` | `serial_number`, `zone`, `customer_category`, `forecast_m3`, `horizon_days`, `readings` = liste de `[date, index_m3]` (index **cumulé**) | `consumption.WaterMeter`, `consumption.MeterReading` (Student 2) |
| `incidents` | `reference`, `meter`, `suspected_pipe`, `suspected_pump`, `position_on_pipe` (0 à 1, défaut 0,5), `technician`, `rule`, `status`, `description`, `opened_at`, `resolved_at` | `quality_leaks.LeakIncident` (Student 3) |

`history` est une liste `[date, statut, risque]`. Le modèle actuel ne garde que la dernière prédiction : la liste contient donc un seul point. Une table d'historique des prédictions permettrait d'animer la chronologie.

## Ce que Student 2 et Student 3 doivent respecter

`infrastructure/services/integration.py` lit leurs modèles avec `apps.get_model()`. Tant qu'ils n'existent pas, `meters` et `incidents` sont vides et rien ne casse.

Noms de champs attendus :

- `consumption.WaterMeter` : `zone` (FK `infrastructure.WaterZone`), `serial_number`, `customer_category`, `forecast_m3`, `horizon_days`
- `consumption.MeterReading` : `meter` (FK `WaterMeter`), `recorded_at`, `index_m3`
- `quality_leaks.LeakIncident` : `meter`, `suspected_pipe` (FK `infrastructure.WaterPipe`), `suspected_pump` (FK `infrastructure.WaterPump`), `technician` (FK `accounts.NetworkTechnician`), `rule`, `description`, `opened_at`, `resolved_at` ; optionnel : `position_on_pipe`, `reference`

Un nom différent ? Adapter `integration.py` dans la même pull request.
