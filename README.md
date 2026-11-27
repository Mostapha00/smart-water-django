# AquaMind

Application Django pour suivre la consommation d'eau d'un site (école, usine, bâtiment public), repérer les problèmes (fuites, pannes) et choisir des actions d'économie. Contexte : Tunisie, tarifs SONEDE / ONAS paramétrables, données saisies ou importées (pas de capteurs IoT).

Projet d'école mené par 4 étudiants : une app Django par étudiant, dans un seul projet (monolithe modulaire).

| App | Module | Responsable | État |
| --- | --- | --- | --- |
| `accounts` | Profils partagés : `UserProfile` (User abstrait), `NetworkTechnician`, `AuditManager` | Toute l'équipe | Fait |
| `infrastructure` | Sites, zones, canalisations, pompes, maintenance, maquette 3D | Student 1 | Fait |
| `consumption` | Compteurs, relevés, tarifs SONEDE/ONAS, factures | Student 2 | Disponible |
| `quality_leaks` | Analyses d'eau, règles d'alerte, incidents de fuite | Student 3 | Disponible |
| `sustainability` | Cibles, projets d'économie, optimisation budgétaire, audits PDF et BI exécutive | Student 4 | Disponible |

Chaque module contient ses modèles, migrations, vues, tests et interfaces d'administration.

## Démarrage rapide

Prérequis : Python 3.12 et Git. PostgreSQL 16 est optionnel en développement (SQLite par défaut).

```bash
git clone https://github.com/<votre-compte>/aquamind.git
cd aquamind
python -m venv .venv
# Windows : .venv\Scripts\activate    ·    macOS / Linux : source .venv/bin/activate
pip install -r requirements-ml.txt   # application + modèles d'IA (ou requirements.txt sans l'IA)
cp .env.example .env          # Windows : copy .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo    # site de démonstration « École primaire Ennour »
python manage.py seed_tekup   # site « Technopole El Ghazala » (données estimées)
python manage.py train_models # entraîne les modèles d'IA et recalcule les prédictions
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

## Intelligence artificielle

```bash
pip install -r requirements-ml.txt
python manage.py train_models                # entraîne puis recalcule tout (à relancer quand les données changent)
python manage.py train_models --predict-only # recalcule sans réentraîner
```

Les modèles sont entraînés **hors requête web** et enregistrés dans `media/ml/` (non versionné, réglable par `AQUAMIND_ML_DIR`). Sans modèle, ou sans `requirements-ml.txt`, chaque fonction utilise une **règle simple** : l'application fonctionne toujours. Chaque page affiche l'origine du résultat : badge vert **Modèle IA**, orange **Modèle IA · démo**, gris **Règle** (balise `{% ml_badge %}`).

| Fonction | Modèle | Règle de secours | Code |
| --- | --- | --- | --- |
| Risque de panne à 30 jours | **Random Forest** (scikit-learn) | `baseline-0.1` (âge, pannes, statut) | `infrastructure/services/risk.py`, `risk_training.py` |
| Fuites possibles sur les relevés | **Isolation Forest** (non supervisé) | `rolling-ratio-1` (> 1,4 × moyenne) | `consumption/services/anomaly.py` |
| Prévision de consommation | **LightGBM** (un modèle pour tous les compteurs) | `average-daily-1` (moyenne journalière) | `consumption/services/forecasting.py` |
| Choix des projets sous budget | **PuLP** (programmation linéaire, optimal) | `greedy-fallback` (meilleur ratio d'abord) | `sustainability/services/optimization.py` |
| Potabilité de l'eau | — | `rules-v1` (seuils pH, turbidité, chlore, conductivité) | `quality_leaks/models.py` |

Choix importants, à connaître pour la soutenance :

- **Random Forest** : apprend sur des « photos » mensuelles des 24 derniers mois. Étiquette = « une intervention corrective a eu lieu dans les 30 jours ». Chaque photo n'utilise que les interventions **antérieures** (pas de triche). Le statut actuel n'est pas une variable : son historique n'est pas enregistré. Avec moins de 30 pannes, le modèle est marqué **démo** : les données de démonstration n'en ont que quelques-unes.
- **Isolation Forest** : ne demande aucun exemple de fuite. Chaque relevé est comparé au niveau habituel de **son** compteur. Il est signalé seulement s'il est atypique **et** au moins 30 % au-dessus de l'habitude : une baisse n'est pas une fuite, un mois de février plus court non plus. Lancé automatiquement à chaque relevé saisi ou importé. Le score n'est pas une probabilité.
- **LightGBM** : apprend un multiplicateur saisonnier (« en août × 0,3 ») par rapport au niveau habituel du compteur. Il est testé sur le dernier mois de chaque compteur et **activé seulement s'il fait mieux que la moyenne simple**. Avec les 10 mois de données de démonstration, ce n'est pas le cas (un mois jamais vu ne peut pas être appris) : la règle reste utilisée, et `train_models` l'explique. Il faut au moins un an d'historique réel.
- **PuLP** : trouve la meilleure combinaison de projets, là où le tri glouton peut se tromper (exemple dans `infrastructure/tests/test_ml.py`).

Les tests (`infrastructure/tests/test_ml.py`) vérifient chaque modèle sur des données construites où la bonne réponse est connue, et utilisent un dossier de modèles vide (`config/test_runner.py`) : un modèle entraîné en local ne change jamais le résultat des tests.

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
├── sustainability/      cibles, projets, optimisation et audits PDF
├── templates/           base.html, connexion
├── static/              CSS commun
└── docs/                contrat JSON, maquette 3D autonome
```
