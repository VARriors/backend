from flask import Blueprint, jsonify, request
from app import db
from bson.objectid import ObjectId
from app.services.candidate_questionnaire_service import now_iso
from app.services.ledger_service import append_event, create_application

employers_bp = Blueprint('employers', __name__)
jobs_collection = db['jobs']
employers_collection = db['employers']
applications_collection = db['applications']


def _find_application_for_employer(employer_id, application_id):
    try:
        object_id = ObjectId(application_id)
    except Exception:
        return None

    app_doc = applications_collection.find_one({"_id": object_id})
    if not app_doc:
        return None
    if app_doc.get("employer_id") != employer_id:
        return "forbidden"
    return app_doc


def _ensure_ledger_link(app_doc):
    if app_doc.get("ledger_application_ref"):
        return {
            "application_ref": app_doc.get("ledger_application_ref"),
            "application_commitment": app_doc.get("ledger_application_commitment"),
            "claim_token": app_doc.get("ledger_claim_token"),
        }

    ledger_result = create_application(
        candidate_id=app_doc.get("candidate_id"),
        employer_id=app_doc.get("employer_id"),
        job_id=app_doc.get("job_id"),
        metadata={"origin": "legacy_application_link"},
    )
    applications_collection.update_one(
        {"_id": app_doc["_id"]},
        {
            "$set": {
                "ledger_application_ref": ledger_result["application_ref"],
                "ledger_application_commitment": ledger_result["application_commitment"],
                "ledger_latest_status": "SENT",
                "ledger_claim_token": ledger_result["claim_token"],
                "updated_at": now_iso(),
            }
        },
    )
    return ledger_result


def _append_employer_status(app_doc, status_code, idempotency_key, note=None, metadata=None):
    ledger_data = _ensure_ledger_link(app_doc)
    event = append_event(
        application_ref=ledger_data["application_ref"],
        status_code=status_code,
        actor_role="employer",
        actor_id=app_doc.get("employer_id"),
        idempotency_key=idempotency_key,
        note=note,
        metadata=metadata or {},
    )
    applications_collection.update_one(
        {"_id": app_doc["_id"]},
        {
            "$set": {
                "status": status_code,
                "ledger_latest_status": status_code,
                "ledger_last_event_hash": event.get("event_hash"),
                "status_history_synced_at": now_iso(),
                "updated_at": now_iso(),
            }
        },
    )
    return ledger_data, event

@employers_bp.route('/jobs', methods=['GET', 'POST'])
def jobs():
    if request.method == 'GET':
        offer_list = list(jobs_collection.find({}))
        for offer in offer_list:
            offer['_id'] = str(offer['_id'])
        return jsonify(offer_list), 200
        
    if request.method == 'POST':
        new_offer = request.json
        if not new_offer or 'title' not in new_offer:
            return jsonify({"error": "Missing title in payload"}), 400
        
        result = jobs_collection.insert_one(new_offer)
        return jsonify({"message": "Job offer created", "id": str(result.inserted_id)}), 201

@employers_bp.route('/applications/<employer_id>', methods=['GET'])
def get_employer_applications(employer_id):
    apps = list(applications_collection.find({"employer_id": employer_id}))
    for a in apps:
        a['_id'] = str(a['_id'])
    return jsonify(apps), 200


@employers_bp.route('/applications/<employer_id>/<application_id>/viewed', methods=['PATCH'])
def mark_application_viewed(employer_id, application_id):
    payload = request.json or {}
    app_doc = _find_application_for_employer(employer_id, application_id)
    if app_doc is None:
        return jsonify({"error": "Application not found"}), 404
    if app_doc == "forbidden":
        return jsonify({"error": "Application does not belong to employer"}), 403

    idempotency_key = payload.get("idempotency_key") or f"viewed-{application_id}"
    note = payload.get("note") or "Employer viewed application"

    try:
        ledger_data, event = _append_employer_status(
            app_doc=app_doc,
            status_code="VIEWED",
            idempotency_key=idempotency_key,
            note=note,
            metadata={"origin": "employer_viewed"},
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 409
    except LookupError as error:
        return jsonify({"error": str(error)}), 404

    return jsonify({
        "message": "Application marked as viewed",
        "application_id": application_id,
        "status": "VIEWED",
        "ledger": {
            "applicationRef": ledger_data["application_ref"],
            "event": event,
        },
    }), 200


@employers_bp.route('/applications/<employer_id>/<application_id>/decision', methods=['PATCH'])
def decide_application(employer_id, application_id):
    payload = request.json or {}
    decision = payload.get("decision")
    if decision not in ["ACCEPTED", "REJECTED"]:
        return jsonify({"error": "decision must be ACCEPTED or REJECTED"}), 400

    app_doc = _find_application_for_employer(employer_id, application_id)
    if app_doc is None:
        return jsonify({"error": "Application not found"}), 404
    if app_doc == "forbidden":
        return jsonify({"error": "Application does not belong to employer"}), 403

    idempotency_key = payload.get("idempotency_key") or f"decision-{decision.lower()}-{application_id}"
    note = payload.get("note") or f"Employer decision: {decision}"

    try:
        ledger_data, event = _append_employer_status(
            app_doc=app_doc,
            status_code=decision,
            idempotency_key=idempotency_key,
            note=note,
            metadata={"origin": "employer_decision"},
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 409
    except LookupError as error:
        return jsonify({"error": str(error)}), 404

    return jsonify({
        "message": "Application decision saved",
        "application_id": application_id,
        "status": decision,
        "ledger": {
            "applicationRef": ledger_data["application_ref"],
            "event": event,
        },
    }), 200