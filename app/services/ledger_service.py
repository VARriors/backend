import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

from pymongo import ASCENDING

from app import db


applications_collection = db["ledger_applications"]
events_collection = db["ledger_events"]
documents_collection = db["ledger_application_documents"]

ALLOWED_STATUS_CODES = {
    "SENT",
    "RECEIVED",
    "VIEWED",
    "SHORTLISTED",
    "INTERVIEW",
    "ACCEPTED",
    "REJECTED",
    "WITHDRAWN",
    "DISPUTED",
    "CORRECTED",
}

ALLOWED_TRANSITIONS = {
    "SENT": {"RECEIVED", "VIEWED", "SHORTLISTED", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "DISPUTED"},
    "RECEIVED": {"VIEWED", "SHORTLISTED", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "DISPUTED"},
    "VIEWED": {"SHORTLISTED", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "DISPUTED"},
    "SHORTLISTED": {"INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN", "DISPUTED"},
    "INTERVIEW": {"ACCEPTED", "REJECTED", "WITHDRAWN", "DISPUTED"},
    "ACCEPTED": {"DISPUTED", "CORRECTED"},
    "REJECTED": {"DISPUTED", "CORRECTED"},
    "WITHDRAWN": {"DISPUTED", "CORRECTED"},
    "DISPUTED": {"CORRECTED"},
    "CORRECTED": {"VIEWED", "SHORTLISTED", "INTERVIEW", "ACCEPTED", "REJECTED", "WITHDRAWN"},
}

EMPLOYER_ALLOWED_STATUS_CODES = {
    "RECEIVED",
    "VIEWED",
    "SHORTLISTED",
    "INTERVIEW",
    "ACCEPTED",
    "REJECTED",
}

CANDIDATE_ALLOWED_STATUS_CODES = {
    "WITHDRAWN",
    "DISPUTED",
}

ALLOWED_DOCUMENT_TYPES = {
    "disability_statement",
    "driving_license",
    "criminal_record",
    "sanitary_book",
}

ALLOWED_DOCUMENT_VERIFICATION_STATUSES = {
    "verified",
    "declared",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def canonical_json(payload):
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def sha256_hex(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_sha256_hex(secret, value):
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_application_ref():
    return f"app_{secrets.token_urlsafe(18)}"


def generate_claim_token():
    return secrets.token_urlsafe(32)


def hash_claim_token(claim_token):
    return sha256_hex(claim_token)


def verify_claim_token(claim_token, claim_token_hash):
    if not claim_token or not claim_token_hash:
        return False
    return hmac.compare_digest(hash_claim_token(claim_token), claim_token_hash)


def build_application_commitment(candidate_id, employer_id, job_id, nonce):
    commitment_payload = canonical_json({
        "candidate_id": candidate_id,
        "employer_id": employer_id,
        "job_id": job_id,
        "nonce": nonce,
    })
    return sha256_hex(commitment_payload)


def build_signature_payload(application_ref, status_code, actor_role, actor_id, idempotency_key):
    return canonical_json({
        "application_ref": application_ref,
        "status_code": status_code,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
    })


def verify_employer_signature(application_ref, status_code, actor_role, actor_id, idempotency_key, signature):
    secret = os.getenv("LEDGER_EMPLOYER_SHARED_SECRET", "demo-ledger-secret")
    expected = hmac_sha256_hex(
        secret,
        build_signature_payload(application_ref, status_code, actor_role, actor_id, idempotency_key),
    )
    return hmac.compare_digest(expected, signature or "")


def get_signature_preview(application_ref, status_code, actor_role, actor_id, idempotency_key):
    payload_obj = {
        "application_ref": application_ref,
        "status_code": status_code,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
    }
    payload = build_signature_payload(
        application_ref=application_ref,
        status_code=status_code,
        actor_role=actor_role,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )
    return {
        "payload_object": payload_obj,
        "canonical_payload": payload,
        "payload_sha256": sha256_hex(payload),
    }


def ensure_indexes():
    applications_collection.create_index([("application_ref", ASCENDING)], unique=True)
    applications_collection.create_index([("candidate_id", ASCENDING)])
    applications_collection.create_index([("employer_id", ASCENDING)])

    events_collection.create_index([("application_ref", ASCENDING), ("sequence", ASCENDING)], unique=True)
    events_collection.create_index([("application_ref", ASCENDING), ("event_time", ASCENDING)])
    events_collection.create_index([("application_ref", ASCENDING), ("actor_role", ASCENDING), ("actor_id", ASCENDING), ("idempotency_key", ASCENDING)])

    documents_collection.create_index([("application_ref", ASCENDING), ("sequence", ASCENDING)], unique=True)
    documents_collection.create_index([("application_ref", ASCENDING), ("attached_at", ASCENDING)])
    documents_collection.create_index([("application_ref", ASCENDING), ("document_type", ASCENDING)])
    documents_collection.create_index([("application_ref", ASCENDING), ("actor_role", ASCENDING), ("actor_id", ASCENDING), ("idempotency_key", ASCENDING)])


def create_application(candidate_id, employer_id, job_id, metadata=None):
    application_ref = generate_application_ref()
    claim_token = generate_claim_token()
    nonce = secrets.token_urlsafe(16)

    document = {
        "application_ref": application_ref,
        "candidate_id": candidate_id,
        "employer_id": employer_id,
        "job_id": job_id,
        "application_commitment": build_application_commitment(candidate_id, employer_id, job_id, nonce),
        "claim_token_hash": hash_claim_token(claim_token),
        "nonce": nonce,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "latest_status": None,
        "metadata": metadata or {},
    }

    applications_collection.insert_one(document)
    event = append_event(
        application_ref=application_ref,
        status_code="SENT",
        actor_role="platform",
        actor_id="platform",
        idempotency_key=f"init-{secrets.token_hex(8)}",
        note="Application created",
        metadata={"origin": "application_create"},
    )

    return {
        "application_ref": application_ref,
        "claim_token": claim_token,
        "application_commitment": document["application_commitment"],
        "initial_event": event,
    }


def get_application(application_ref):
    return applications_collection.find_one({"application_ref": application_ref})


def get_events(application_ref):
    return list(events_collection.find({"application_ref": application_ref}).sort("sequence", ASCENDING))


def _event_hash_payload(event):
    return {
        "application_ref": event["application_ref"],
        "sequence": event["sequence"],
        "status_code": event["status_code"],
        "event_time": event["event_time"],
        "actor_role": event["actor_role"],
        "actor_id": event["actor_id"],
        "idempotency_key": event["idempotency_key"],
        "note": event.get("note"),
        "metadata": event.get("metadata", {}),
        "previous_event_hash": event.get("previous_event_hash"),
        "policy_version": event.get("policy_version", "v1"),
    }


def _last_event(application_ref):
    return events_collection.find_one({"application_ref": application_ref}, sort=[("sequence", -1)])


def _last_document(application_ref):
    return documents_collection.find_one({"application_ref": application_ref}, sort=[("sequence", -1)])


def _normalize_document_type(document_type):
    if not isinstance(document_type, str):
        return None
    return document_type.strip().lower()


def _normalize_verification_status(verification_status):
    if not isinstance(verification_status, str):
        return None
    return verification_status.strip().lower()


def _document_hash_payload(document):
    return {
        "application_ref": document["application_ref"],
        "sequence": document["sequence"],
        "document_type": document["document_type"],
        "provider": document["provider"],
        "verification_status": document["verification_status"],
        "verified_at": document.get("verified_at"),
        "valid_until": document.get("valid_until"),
        "document_reference": document.get("document_reference"),
        "attached_at": document["attached_at"],
        "actor_role": document["actor_role"],
        "actor_id": document["actor_id"],
        "idempotency_key": document["idempotency_key"],
        "note": document.get("note"),
        "metadata": document.get("metadata", {}),
        "previous_event_hash": document.get("previous_event_hash"),
        "policy_version": document.get("policy_version", "v1-documents"),
    }


def append_event(application_ref, status_code, actor_role, actor_id, idempotency_key, note=None, metadata=None):
    if status_code not in ALLOWED_STATUS_CODES:
        raise ValueError("Invalid status_code")

    application = get_application(application_ref)
    if not application:
        raise LookupError("Application not found")

    current_status = application.get("latest_status")
    if current_status:
        allowed_next = ALLOWED_TRANSITIONS.get(current_status, set())
        if status_code not in allowed_next:
            raise ValueError(
                f"Invalid status transition: {current_status} -> {status_code}"
            )

    existing = events_collection.find_one({
        "application_ref": application_ref,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
    })
    if existing:
        existing["_id"] = str(existing["_id"])
        return existing

    last_event = _last_event(application_ref)
    sequence = (last_event.get("sequence", 0) + 1) if last_event else 1
    previous_event_hash = last_event.get("event_hash") if last_event else None

    event = {
        "application_ref": application_ref,
        "sequence": sequence,
        "status_code": status_code,
        "event_time": now_iso(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "note": note,
        "metadata": metadata or {},
        "previous_event_hash": previous_event_hash,
        "policy_version": "v1",
    }

    event["event_hash"] = sha256_hex(canonical_json(_event_hash_payload(event)))
    result = events_collection.insert_one(event)

    applications_collection.update_one(
        {"application_ref": application_ref},
        {
            "$set": {
                "latest_status": status_code,
                "updated_at": now_iso(),
            }
        },
    )

    event["_id"] = str(result.inserted_id)
    return event


def append_application_document(
    application_ref,
    document_type,
    actor_role,
    actor_id,
    idempotency_key,
    verification_status="verified",
    provider="mobywatel",
    verified_at=None,
    valid_until=None,
    document_reference=None,
    note=None,
    metadata=None,
):
    normalized_document_type = _normalize_document_type(document_type)
    if normalized_document_type not in ALLOWED_DOCUMENT_TYPES:
        raise ValueError("Invalid document_type")

    normalized_verification_status = _normalize_verification_status(verification_status)
    if normalized_verification_status not in ALLOWED_DOCUMENT_VERIFICATION_STATUSES:
        raise ValueError("Invalid verification_status")

    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("idempotency_key is required")

    application = get_application(application_ref)
    if not application:
        raise LookupError("Application not found")

    existing = documents_collection.find_one({
        "application_ref": application_ref,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
    })
    if existing:
        existing["_id"] = str(existing["_id"])
        return existing

    last_document = _last_document(application_ref)
    sequence = (last_document.get("sequence", 0) + 1) if last_document else 1
    previous_event_hash = last_document.get("event_hash") if last_document else None

    document_event = {
        "application_ref": application_ref,
        "sequence": sequence,
        "document_type": normalized_document_type,
        "provider": provider,
        "verification_status": normalized_verification_status,
        "verified_at": verified_at,
        "valid_until": valid_until,
        "document_reference": document_reference,
        "attached_at": now_iso(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
        "note": note,
        "metadata": metadata or {},
        "previous_event_hash": previous_event_hash,
        "policy_version": "v1-documents",
    }

    document_event["event_hash"] = sha256_hex(canonical_json(_document_hash_payload(document_event)))
    result = documents_collection.insert_one(document_event)

    applications_collection.update_one(
        {"application_ref": application_ref},
        {
            "$set": {
                "updated_at": now_iso(),
            }
        },
    )

    document_event["_id"] = str(result.inserted_id)
    return document_event


def get_application_documents(application_ref):
    return list(documents_collection.find({"application_ref": application_ref}).sort("sequence", ASCENDING))


def verify_event_chain(application_ref):
    events = get_events(application_ref)
    issues = []

    previous_hash = None
    for index, event in enumerate(events):
        if event.get("sequence") != index + 1:
            issues.append(f"Invalid sequence at index {index}")

        if event.get("previous_event_hash") != previous_hash:
            issues.append(f"Broken hash link at sequence {event.get('sequence')}")

        expected_hash = sha256_hex(canonical_json(_event_hash_payload(event)))
        if event.get("event_hash") != expected_hash:
            issues.append(f"Invalid event hash at sequence {event.get('sequence')}")

        previous_hash = event.get("event_hash")

    return {
        "application_ref": application_ref,
        "valid": len(issues) == 0,
        "issues": issues,
        "event_count": len(events),
    }
