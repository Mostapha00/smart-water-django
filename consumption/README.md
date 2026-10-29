# Student 2: consumption and billing backend

This module implements meters, cumulative readings, configurable SONEDE/ONAS tariff bands, bills, CSV imports, and consumption forecasting. It uses Django sessions, model permissions, CSRF protection, the existing admin, and SQLite or PostgreSQL. It adds no REST framework dependency and does not change the shared profile models or 3D JSON contract.

## Run it

From the repository root:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_consumption
python manage.py runserver
```

Log in at `/connexion/`. Open `/consommation/` for API discovery and a CSRF token. Staff with the relevant permissions can also manage data at `/admin/consumption/`.

`seed_consumption` creates a demo meter and 46 daily readings on Student 1's demo site. It is safe to repeat. Its customer category is `DEMO_NOT_OFFICIAL`; its rates are fictional examples. It does not change other customers' tariffs.

## API routes

All paths below start with `/consommation/`.

| Path | Methods | Purpose |
| --- | --- | --- |
| `/` | GET | API discovery and session CSRF token |
| `api/meters/` | GET, POST | List or create meters |
| `api/meters/<id>/` | GET, PATCH, PUT, DELETE | Read, update, or delete a meter |
| `api/readings/` | GET, POST | List or create cumulative readings |
| `api/readings/<id>/` | GET, PATCH, PUT, DELETE | Read, update, or delete a reading |
| `api/tariffs/` | GET, POST | List or create tariff bands |
| `api/tariffs/<id>/` | GET, PATCH, PUT, DELETE | Read, update, or delete a tariff band |
| `api/bills/` | GET, POST | List or calculate a draft bill |
| `api/bills/<id>/` | GET, PATCH, PUT, DELETE | Read, recalculate, or delete a draft |
| `api/meters/<id>/import/` | POST | Import a multipart CSV field named `file` |
| `api/meters/<id>/consumption/?start=YYYY-MM-DD&end=YYYY-MM-DD` | GET | Calculate an exact boundary index difference |
| `api/meters/<id>/forecast/` | POST | Persist a forecast and return tariff-band alerts |
| `api/bills/<id>/issue/` | POST | Recalculate and freeze a bill |

List responses have `count`, `page`, and `results`. Use `?page=1&limit=50`; the maximum limit is 200. Meter lists accept `site` or `zone`; reading and bill lists accept `meter`; tariffs accept `service` or `customer_category`. PATCH and PUT update the supplied writable fields. Unknown and computed fields are rejected.

Amounts and cumulative indexes are JSON strings to preserve decimal precision. Field names match `models.py`. The first reading has no consumption value; later consumption is the difference from the preceding reading.

### Permissions and CSRF

Anonymous requests receive 401. CRUD uses Django's `view`, `add`, `change`, and `delete` permissions for each model. CSV imports require `add_meterreading`; forecasts require `change_watermeter`; issuing requires `change_waterbill`.

Writes use the existing authenticated session and an `X-CSRFToken` header. They are not CSRF-exempt. Invalid input returns 400, insufficient permissions 403, missing records 404, unsupported methods 405, and protected relations or database conflicts 409. Standard Django CSRF rejections are 403 responses.

After logging in, this browser-console example creates a meter. Replace `zone` with an existing zone ID:

```javascript
const info = await (await fetch('/consommation/')).json();
const headers = {'Content-Type': 'application/json', 'X-CSRFToken': info.csrf_token};
await fetch('/consommation/api/meters/', {
  method: 'POST', headers,
  body: JSON.stringify({zone: 1, serial_number: 'M-NEW', customer_category: 'school', installed_on: '2026-01-01'})
});
```

A reading payload is:

```json
{"meter": 1, "recorded_at": "2026-01-01T00:00:00+01:00", "index_m3": "1000.125"}
```

An omitted reading source defaults to `manual`. Only the CSV importer automatically marks rows `csv`. Readings before installation, decreasing indexes, duplicate timestamps, and invalid decimals are rejected. Changing readings clears the meter's cached forecast.

### CSV imports

The header must be exactly `recorded_at,index_m3`. UTF-8 BOMs are accepted. Use ISO timestamps; timestamps without an offset are interpreted in `Africa/Tunis`.

```csv
recorded_at,index_m3
2026-01-01T00:00:00+01:00,1000.000
2026-01-02T00:00:00+01:00,1002.125
```

The importer accepts unsorted rows, validates them against the complete stored sequence, and commits the file atomically. Identical rows are skipped on a repeated import. Conflicting duplicates or any invalid row reject the whole file. Limits are 2 MiB and 10,000 rows. Index resets need a new meter record; they are not silently interpreted as negative consumption.

## Billing rules

Create a bill with:

```json
{"meter": 1, "period_start": "2026-01-01", "period_end": "2026-04-01", "include_onas": true}
```

The end date is exclusive. Exact readings at local midnight on both dates are required. The backend never interpolates missing billing indexes. Omitting `include_onas` defaults to true; use false when ONAS is not applicable.

Configure tariffs before calculating bills. Bands distinguish service, customer category, inclusive validity dates, a reference duration, fixed fee, and calculation mode:

- `global`: the reached band's price applies to the whole volume.
- `marginal`: each reached band's price applies only to its portion of the volume.

Volume bounds are half-open: lower bound included, upper bound excluded. Bounds and the fixed fee are prorated by actual billing days divided by `reference_period_days`. The fixed fee is charged once per service. Each service's contiguous band set must start at zero and share its validity dates, mode, fixed fee, and reference duration. Gaps, overlapping bands, uncovered volumes, and periods crossing a tariff change are rejected. Split such periods explicitly.

The engine produces educational estimates excluding taxes. It does not claim to encode every category-specific ONAS rule. No official prices are bundled. Enter parameters from the applicable official tariff before using a real estimate. [SONEDE explains the separate fixed and volume-based service charges](https://www.sonede.com.tn/tout-savoir-sur-leau/la-facture-deau-methodes-de-paiement/).

Issuing recalculates the draft, stores the boundary readings and tariff parameters in a JSON snapshot, and freezes the bill. Issuing twice returns the same bill. Issued bills cannot be edited or deleted, their covered readings cannot be changed, and overlapping issued periods are rejected. Drafts can be recalculated by PATCHing their inputs or sending an empty JSON object. Amounts use Decimal with three-place TND rounding.

## Forecasting

The dependency-free baseline uses the mean daily rate over the latest 90 intervals, accounting for real elapsed time. It is labelled `mean-daily-rate-baseline-1`, not represented as a trained model. Forecasts begin at the latest reading and support a 1–365 day horizon. Returned SONEDE/ONAS alerts identify whether the forecast reaches a band above the first; missing tariffs are reported as unavailable, not guessed.

```bash
python manage.py forecast_consumption --meter 1 --days 30
```

For optional LightGBM training:

```bash
pip install -r requirements-ml.txt
python manage.py train_consumption_model 1
python manage.py forecast_consumption --meter 1 --days 30
```

Training needs at least 40 consecutive daily readings. Sparse monthly indexes remain usable for the baseline but are never fabricated into daily ML data. Training uses weekday, month, previous-day consumption, and the previous seven-day mean. A chronological holdout MAE is reported before fitting the final model. This is a demonstration pipeline, not a validated accuracy claim. The [LightGBM regressor API](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRegressor.html) supplies the estimator.

Operator-created artifacts are stored under `media/consumption_models`, configurable through `AQUAMIND_CONSUMPTION_MODEL_DIR`. They are not committed and cannot be uploaded through the API. If training readings change, the model must be retrained. Inference persists volume, horizon, version, and calculation time together.

`MeterReading.detect_anomaly()` remains Student 3's documented integration point. Student 2 does not invent anomaly scores or implement Student 3's leak classifier.

## Team integration and tests

`WaterMeter.zone`, `serial_number`, `customer_category`, `forecast_m3`, `horizon_days`, and `MeterReading.meter` with `related_name='readings'` preserve `docs/CONTRAT_JSON.md`. Meters and their cumulative readings appear automatically in Student 1's 3D payload. The existing zone coverage validator now detects empty zones; no new cross-app schema is introduced. Deleting the final meter is not globally prohibited because zone commissioning remains owned by the infrastructure workflow.

```bash
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py test
```

Tests exercise reading chronology, atomic/idempotent CSV imports, tariffs, decimal amounts, issuing and snapshots, authentication, permissions, CSRF, API/admin paths, demo seeding, and the 3D integration. Optional LightGBM tests run when its dependencies are installed. Base installation still runs without ML packages.