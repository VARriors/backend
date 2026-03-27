# mPraca Backend API

Flask + MongoDB backend for mPraca demo functionality.

## Run Locally

1. Install dependencies: `pip install -r requirements.txt`
2. Set MongoDB URI (optional): `export MONGO_URI=mongodb://localhost:27017/mpraca`
3. Start server: `python run.py`

Server runs on `http://127.0.0.1:5000`.

## Health

- `GET /health`
- `GET /`

## Existing Endpoints

### Candidates

- `GET /api/candidates/`
- `GET /api/candidates/profile/<candidate_id>`
- `POST /api/candidates/cv`

### Employers

- `GET /api/employers/jobs`
- `POST /api/employers/jobs`
- `GET /api/employers/applications/<employer_id>`

### Matching

- `GET /api/matching/<candidate_id>`
- `GET /api/matching/employer/<job_id>`

## New: CV Questionnaire and Verification API

The questionnaire is split by source and verification authority.

- mObywatel system fields: `imie`, `nazwisko`, `pesel`, `dowod`, `niepelnosprawnosc`
- Urzad Pracy system fields: `doswiadczenia_zawodowe`
- User entered fields: `nr_telefonu`, `email`, `preferencje`, `obszar_poszukiwan`, `jezyki`, `szkolenia`, `kursy`, `certyfikaty`, `aktywnosc_dodatkowa`

Each field has per-field verification metadata.

- `source`: `mobywatel` | `urzad_pracy` | `user`
- `status`: `verified` | `pending` | `unverified` | `rejected`
- `verified_by`, `verified_at`, `note`

### Endpoints

- `GET /api/candidates/questionnaire/<candidate_id>`
  - Returns full questionnaire state, source map, and completion status.

- `PUT /api/candidates/questionnaire/<candidate_id>/user-input`
  - Upserts user-owned fields only.
  - Request body:

```json
{
  "fields": {
    "nr_telefonu": "+48500111222",
    "email": "jan.kowalski@example.com",
    "preferencje": ["IT", "Administracja"],
    "obszar_poszukiwan": "Warszawa i okolice"
  }
}
```

- `PUT /api/candidates/questionnaire/<candidate_id>/mobywatel`
  - Merges mObywatel fields and marks them `verified` by `mobywatel`.
  - Request body:

```json
{
  "fields": {
    "imie": "Jan",
    "nazwisko": "Kowalski",
    "pesel": "90010112345",
    "dowod": "ABC123456",
    "niepelnosprawnosc": false
  }
}
```

- `PUT /api/candidates/questionnaire/<candidate_id>/urzad-pracy`
  - Merges Urzad Pracy data and marks it `verified` by `urzad_pracy`.
  - Request body:

```json
{
  "fields": {
    "doswiadczenia_zawodowe": [
      {
        "stanowisko": "Specjalista",
        "firma": "Firma X",
        "od": "2022-01",
        "do": "2024-12"
      }
    ]
  }
}
```

- `GET /api/candidates/questionnaire/<candidate_id>/verification-summary`
  - Returns aggregate status counters and per-field verification details.

- `GET /api/candidates/cv/status/<candidate_id>`
  - CVGuard-friendly status endpoint.
  - Response contains `has_cv`, `questionnaire_complete`, `missing_fields`, `next_step`.

- `POST /api/candidates/questionnaire/seed-demo`
  - Creates demo candidate with prefilled questionnaire and optional CV.
  - Request body (optional):

```json
{
  "first_name": "Jan",
  "last_name": "Kowalski",
  "create_cv": true
}
```

## Validation Rules

- `pesel`: exactly 11 digits
- `email`: basic email format
- `nr_telefonu`: `+48XXXXXXXXX` or `XXXXXXXXX`
- `preferencje`, `jezyki`, `szkolenia`, `kursy`, `certyfikaty`: array of strings
- `doswiadczenia_zawodowe`: array

## Demo Flow (Quick Test)

1. `POST /api/candidates/questionnaire/seed-demo`
2. `GET /api/candidates/questionnaire/<candidate_id>`
3. `GET /api/candidates/questionnaire/<candidate_id>/verification-summary`
4. `GET /api/candidates/cv/status/<candidate_id>`
5. `GET /api/matching/<candidate_id>`
