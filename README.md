# AquaMind

Application Django pour suivre la consommation d'eau d'un site (école, usine, bâtiment public), repérer les problèmes (fuites, pannes) et choisir des actions d'économie. Contexte : Tunisie, tarifs SONEDE / ONAS paramétrables, données saisies ou importées (pas de capteurs IoT).

Projet d'école mené par 4 étudiants : une app Django par étudiant, dans un seul projet (monolithe modulaire).

| App | Module | Responsable | État |
| --- | --- | --- | --- |
| `accounts` | Profils partagés : `UserProfile` (User abstrait), `NetworkTechnician`, `AuditManager` | Toute l'équipe | Fait |
| `infrastructure` | Sites, zones, canalisations, pompes, maintenance, maquette 3D | Student 1 | Fait |
| `consumption` | Compteurs, relevés, tarifs SONEDE/ONAS, factures | Student 2 | Disponible |
| `quality_leaks` | Analyses d'eau, règles d'alerte, incidents de fuite | Student 3 | Disponible |

Chaque module contient ses modèles, migrations, vues, tests et interfaces d'administration.

## Démarrage rapide

Prérequis : Python 3.12 et Git. PostgreSQL 16 est optionnel en développement (SQLite par défaut).

```bash
git clone https://github.com/<votre-compte>/aquamind.git
cd aquamind
python -m venv .venv
# Windows : .venv\Scripts\activate    ·    macOS / Linux : source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Windows : copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo    # site de démonstration « École primaire Ennour »
python manage.py runserver
```

Ouvrir http://127.0.0.1:8000, se connecter, puis tester les modules depuis la navigation.

### Avec PostgreSQL 16

```sql
CREATE DATABASE aquamind;
CREATE USER aquamind WITH PASSWORD 'motdepasse';
GRANT ALL PRIVILEGES ON DATABASE aquamind TO aquamind;
ALTER DATABASE aquamind OWNER TO aquamind;
```

Puis remplir `POSTGRES_DB=aquamind` et `POSTGRES_PASSWORD` dans `.env`, et relancer `python manage.py migrate`.

## Module infrastructure (Student 1)

Modèles (fichier `infrastructure/models.py`) :

- `Site` : `validate_structure()` vérifie qu'il y a au moins une zone.
- `WaterZone` : composition avec `Site` (supprimer le site supprime ses zones) ; `validate_meter_coverage()`.
- `HydraulicEquipment` (abstraite) → `WaterPipe`, `WaterPump` : `predict_failure_30d()` et `estimate_replacement_cost()` redéfinie dans chaque sous-classe (polymorphisme).
- `MaintenanceWork` : contrainte en base « exactement une cible » (canalisation **ou** pompe) ; `close_work()`.

Pages : liste et fiche des sites, zones, équipements, interventions (création, modification, clôture), admin Django, et **maquette 3D** de chaque site.

### Maquette 3D

Page `sites/<id>/maquette/`, alimentée par `sites/<id>/maquette.json` (Three.js, sans build). Elle affiche les zones, les canalisations souterraines, les pompes, l'état des équipements, le risque de panne, les interventions en cours, une chronologie et un mode « Déplacer les zones » qui enregistre `pos_x` / `pos_y`.

Les compteurs et les fuites apparaissent automatiquement dans la maquette via le contrat décrit dans [`docs/CONTRAT_JSON.md`](docs/CONTRAT_JSON.md).

Une version autonome avec des données fictives complètes (compteurs, fuite, scénario) est dans `docs/maquette-demo-standalone.html` : il suffit de l'ouvrir dans un navigateur.

### IA : risque de panne à 30 jours

`infrastructure/services/risk.py`. Sans modèle entraîné, une **règle de base** transparente (âge, pannes récentes, statut) donne un score étiqueté `baseline-0.1`. Ce n'est pas un modèle validé.

Pour brancher un vrai modèle (Random Forest / XGBoost), l'entraîner **hors requête web**, le sauver avec `joblib`, puis renseigner `AQUAMIND_FAILURE_MODEL_PATH`. Les variables d'entrée sont listées dans `FEATURES`. Recalcul global :

```bash
python manage.py predict_failures
```

### Coûts de remplacement

Les prix unitaires de `AQUAMIND_REPLACEMENT_COSTS` (`config/settings.py`) sont des **valeurs d'exemple**, à remplacer par des prix validés.

## Tests

```bash
python manage.py test
```

GitHub Actions lance les tests à chaque push et pull request (`.github/workflows/tests.yml`).

## Travailler à quatre avec Git

1. Ne jamais travailler directement sur `main`.
2. Une branche par tâche : `git checkout -b feature/consumption-modeles`.
3. Committer souvent, puis `git push -u origin feature/...` et ouvrir une pull request.
4. Un autre membre relit avant la fusion ; les tests doivent passer.
5. Les modèles partagés (`accounts`) et le contrat JSON se modifient seulement après accord de l'équipe.
6. Une seule personne crée les migrations d'une app ; en cas de conflit de migrations, `python manage.py makemigrations --merge`.

## Structure

```
aquamind/
├── config/              paramètres et URL du projet
├── accounts/            profils partagés
├── infrastructure/      Student 1 (modèles, services, vues, templates, static, tests)
├── consumption/         compteurs, relevés, tarifs et factures
├── quality_leaks/       qualité de l'eau, règles et incidents
├── templates/           base.html, connexion
├── static/              CSS commun
└── docs/                contrat JSON, maquette 3D autonome
```
