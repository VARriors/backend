from flask import Blueprint, jsonify, request

from app.services.ledger_service import (
    CANDIDATE_ALLOWED_STATUS_CODES,
    EMPLOYER_ALLOWED_STATUS_CODES,
    append_event,
    build_signature_payload,
    create_application,
    ensure_indexes,
    get_application,
    get_events,
    get_signature_preview,
    verify_claim_token,
    verify_employer_signature,
    verify_event_chain,
)


ledger_bp = Blueprint("ledger", __name__)

# Initialize indexes at import time for MVP simplicity.
ensure_indexes()


def _get_actor_context():
    return {
        "role": (request.headers.get("X-Actor-Role") or "").strip().lower(),
        "id": (request.headers.get("X-Actor-Id") or "").strip(),
        "claim_token": request.headers.get("X-Claim-Token"),
        "audit_reason": request.headers.get("X-Audit-Reason"),
    }


def _authorize_read(application, actor):
    role = actor["role"]
    actor_id = actor["id"]

    if role == "platform":
        return None

    if role == "auditor":
        if not actor.get("audit_reason"):
            return jsonify({"error": "X-Audit-Reason is required for auditor role"}), 400
        return None

    if role == "employer":
        if actor_id != application.get("employer_id"):
            return jsonify({"error": "Employer cannot access foreign application"}), 403
        return None

    if role == "candidate":
        if actor_id != application.get("candidate_id"):
            return jsonify({"error": "Candidate cannot access foreign application"}), 403
        if not verify_claim_token(actor.get("claim_token"), application.get("claim_token_hash")):
            return jsonify({"error": "Invalid claim token"}), 403
        return None

    return jsonify({"error": "Unsupported actor role"}), 400


def _authorize_append(application, actor, status_code, idempotency_key, signature):
    role = actor["role"]
    actor_id = actor["id"]

    if role == "platform":
        return None

    if role == "employer":
        if actor_id != application.get("employer_id"):
            return jsonify({"error": "Employer cannot mutate foreign application"}), 403

        if status_code not in EMPLOYER_ALLOWED_STATUS_CODES:
            return jsonify({"error": "Status not allowed for employer role"}), 403

        if not verify_employer_signature(
            application_ref=application.get("application_ref"),
            status_code=status_code,
            actor_role=role,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            signature=signature,
        ):
            return jsonify({"error": "Invalid employer signature"}), 401

        return None

    if role == "candidate":
        if actor_id != application.get("candidate_id"):
            return jsonify({"error": "Candidate cannot mutate foreign application"}), 403

        if status_code not in CANDIDATE_ALLOWED_STATUS_CODES:
            return jsonify({"error": "Status not allowed for candidate role"}), 403

        if not verify_claim_token(actor.get("claim_token"), application.get("claim_token_hash")):
            return jsonify({"error": "Invalid claim token"}), 403

        return None

    return jsonify({"error": "Unsupported actor role"}), 400


@ledger_bp.route("/applications", methods=["POST"])
def create_application_entry():
    payload = request.json or {}

    candidate_id = payload.get("candidate_id")
    employer_id = payload.get("employer_id")
    job_id = payload.get("job_id")

    if not candidate_id or not employer_id or not job_id:
        return jsonify({"error": "candidate_id, employer_id and job_id are required"}), 400

    result = create_application(
        candidate_id=candidate_id,
        employer_id=employer_id,
        job_id=job_id,
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )

    return jsonify(result), 201


@ledger_bp.route("/applications/<application_ref>/events", methods=["POST"])
def append_application_event(application_ref):
    payload = request.json or {}
    actor = _get_actor_context()

    status_code = payload.get("status_code")
    idempotency_key = payload.get("idempotency_key")
    note = payload.get("note")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    if not status_code or not isinstance(status_code, str):
        return jsonify({"error": "status_code is required"}), 400

    if not idempotency_key or not isinstance(idempotency_key, str):
        return jsonify({"error": "idempotency_key is required"}), 400

    application = get_application(application_ref)
    if not application:
        return jsonify({"error": "Application not found"}), 404

    auth_error = _authorize_append(
        application=application,
        actor=actor,
        status_code=status_code,
        idempotency_key=idempotency_key,
        signature=request.headers.get("X-Signature"),
    )
    if auth_error:
        return auth_error

    try:
        event = append_event(
            application_ref=application_ref,
            status_code=status_code,
            actor_role=actor["role"],
            actor_id=actor["id"],
            idempotency_key=idempotency_key,
            note=note,
            metadata=metadata,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except LookupError as error:
        return jsonify({"error": str(error)}), 404

    return jsonify(event), 201


@ledger_bp.route("/applications/<application_ref>/timeline", methods=["GET"])
def get_application_timeline(application_ref):
    actor = _get_actor_context()
    application = get_application(application_ref)
    if not application:
        return jsonify({"error": "Application not found"}), 404

    auth_error = _authorize_read(application, actor)
    if auth_error:
        return auth_error

    events = get_events(application_ref)
    for event in events:
        event["_id"] = str(event["_id"])

    response = {
        "application_ref": application_ref,
        "application_commitment": application.get("application_commitment"),
        "latest_status": application.get("latest_status"),
        "events": events,
    }
    return jsonify(response), 200


@ledger_bp.route("/applications/<application_ref>/verify-chain", methods=["GET"])
def get_application_chain_verification(application_ref):
    actor = _get_actor_context()
    application = get_application(application_ref)
    if not application:
        return jsonify({"error": "Application not found"}), 404

    auth_error = _authorize_read(application, actor)
    if auth_error:
        return auth_error

    return jsonify(verify_event_chain(application_ref)), 200


@ledger_bp.route("/signatures/preview", methods=["POST"])
def signature_preview():
    payload = request.json or {}
    application_ref = payload.get("application_ref")
    status_code = payload.get("status_code")
    actor_role = (payload.get("actor_role") or "employer").strip().lower()
    actor_id = payload.get("actor_id")
    idempotency_key = payload.get("idempotency_key")
    signature = payload.get("signature")

    if not application_ref or not status_code or not actor_id or not idempotency_key:
        return jsonify({
            "error": "application_ref, status_code, actor_id and idempotency_key are required"
        }), 400

    if actor_role != "employer":
        return jsonify({"error": "Only employer role is supported in signature preview"}), 400

    preview = get_signature_preview(
        application_ref=application_ref,
        status_code=status_code,
        actor_role=actor_role,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )

    response = {
        "preview": preview,
        "verify": {
            "provided": signature is not None,
            "valid": False,
        },
    }

    if signature is not None:
        response["verify"]["valid"] = verify_employer_signature(
            application_ref=application_ref,
            status_code=status_code,
            actor_role=actor_role,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            signature=signature,
        )

    response["signature_payload_example"] = build_signature_payload(
        application_ref=application_ref,
        status_code=status_code,
        actor_role=actor_role,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )

    return jsonify(response), 200
