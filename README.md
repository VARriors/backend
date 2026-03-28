# mPraca Backend

## Run

1. Create venv: `python3 -m venv .venv`
2. Activate venv: `source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Run app: `flask --app run.py --debug run --host 0.0.0.0 --port 5000`

## Health

- `GET /health`

## Ledger MVP (immutable CV status timeline)

This project includes a permissioned-ledger style MVP under `/api/ledger`.

Privacy model:

- No endpoint to list all applications globally.
- Employer can only mutate/read its own application references.
- Candidate can only read/mutate own applications and must provide claim token.
- Full candidate CV/PII is not stored in ledger events, only status event metadata and hashes.

### Endpoints

1. `POST /api/ledger/applications`
2. `POST /api/ledger/applications/<application_ref>/events`
3. `GET /api/ledger/applications/<application_ref>/timeline`
4. `POST /api/ledger/applications/<application_ref>/documents`
5. `GET /api/ledger/applications/<application_ref>/documents`
6. `GET /api/ledger/applications/<application_ref>/verify-chain`
7. `POST /api/ledger/signatures/preview`

### Attach verified document (prototype)

No file upload is stored. Only metadata about the document attachment is persisted.

Request:

```json
{
  "document_type": "driving_license",
  "verification_status": "verified",
  "provider": "mobywatel",
  "verified_at": "2026-03-28T11:22:33Z",
  "valid_until": "2028-03-28T00:00:00Z",
  "document_reference": "mobyw:dl:abc123",
  "idempotency_key": "doc-attach-001",
  "note": "Attached from mObywatel",
  "metadata": {
    "origin": "candidate_apply_flow"
  }
}
```

Allowed `document_type` values:

- `disability_statement`
- `driving_license`
- `criminal_record`
- `sanitary_book`

## Integrated Hooks (apply/viewed/decision)

Ledger events are emitted automatically from existing app flow endpoints.

### Candidate apply hook

- `POST /api/candidate/apply`
- Creates business application (`applications` collection) and linked ledger application.
- Automatically emits initial immutable `SENT` event.

Request:

```json
{
  "candidateId": "cand-123",
  "job_id": "<job_id>",
  "employer_id": "empl-123"
}
```

### Employer viewed hook

- `PATCH /api/employers/applications/<employer_id>/<application_id>/viewed`
- Updates business status and emits ledger `VIEWED` event.

Request:

```json
{
  "idempotency_key": "viewed-001",
  "note": "Viewed by recruiter"
}
```

### Employer final decision hook

- `PATCH /api/employers/applications/<employer_id>/<application_id>/decision`
- Updates business status and emits ledger terminal event (`ACCEPTED` or `REJECTED`).

Request:

```json
{
  "decision": "REJECTED",
  "idempotency_key": "decision-001",
  "note": "Not a fit for this role"
}
```

### Create application

Request:

```json
{
  "candidate_id": "cand-123",
  "employer_id": "empl-123",
  "job_id": "job-123",
  "metadata": {
    "channel": "mpraca"
  }
}
```

Response includes:

- `application_ref` (opaque reference)
- `claim_token` (candidate secret to access timeline)
- `application_commitment`
- initial immutable `SENT` event

### Append event (employer)

Required headers:

- `X-Actor-Role: employer`
- `X-Actor-Id: <employer_id>`
- `X-Signature: <hmac_sha256_hex>`

Signature payload is canonical JSON over:

- `application_ref`, `status_code`, `actor_role`, `actor_id`, `idempotency_key`

Shared secret env:

- `LEDGER_EMPLOYER_SHARED_SECRET`

### Signature preview helper

Use `POST /api/ledger/signatures/preview` to get canonical payload text and digest before signing.

Request:

```json
{
  "application_ref": "app_xxx",
  "status_code": "VIEWED",
  "actor_role": "employer",
  "actor_id": "empl-123",
  "idempotency_key": "viewed-001"
}
```

Optional: include `signature` to run dry-run verification.

Request body:

```json
{
  "status_code": "VIEWED",
  "idempotency_key": "evt-001",
  "note": "Viewed by recruiter"
}
```

### Candidate timeline read

Required headers:

- `X-Actor-Role: candidate`
- `X-Actor-Id: <candidate_id>`
- `X-Claim-Token: <claim_token>`

### Verify chain integrity

`GET /api/ledger/applications/<application_ref>/verify-chain` returns:

- `valid`
- `issues[]`
- `event_count`

## Notes

- This is MVP-grade cryptographic access control using HMAC signatures.
- For production-grade government deployment, move to certificate-based signatures and hardware-backed key management.

## Postman Smoke Test

Collection path:

- `docs/postman/ledger-smoke.postman_collection.json`

Set variables:

- `base_url`
- `candidate_id`
- `employer_id`
- `job_id`

Then run requests in order:

1. Candidate Apply
2. Candidate Timeline
3. Signature Preview for VIEWED
4. Employer Mark Viewed
5. Employer Decision
6. Candidate Timeline (After Decision)
7. Verify Ledger Chain
