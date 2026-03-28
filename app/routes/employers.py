from flask import Blueprint, jsonify, request
from app import db
from bson.objectid import ObjectId
from app.services.candidate_questionnaire_service import now_iso
from app.services.ledger_service import append_event, create_application

employers_bp = Blueprint('employers', __name__)
jobs_collection = db['jobs']
employers_collection = db['employers']
applications_collection = db['applications']
candidates_collection = db['candidates']


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


def _resolve_job(job_id):
    if not isinstance(job_id, str) or not job_id.strip():
        return None

    clean_job_id = job_id.strip()
    try:
        return jobs_collection.find_one({"_id": ObjectId(clean_job_id)})
    except Exception:
        return jobs_collection.find_one({"id": clean_job_id})


def _safe_candidate_preview(candidate_doc, candidate_id):
    questionnaire_fields = ((candidate_doc or {}).get("questionnaire") or {}).get("fields") or {}
    first_name = (
        (candidate_doc or {}).get("first_name")
        or ((questionnaire_fields.get("imie") or {}).get("value"))
    )
    last_name = (
        (candidate_doc or {}).get("last_name")
        or ((questionnaire_fields.get("nazwisko") or {}).get("value"))
    )
    email = (
        (candidate_doc or {}).get("email")
        or ((questionnaire_fields.get("email") or {}).get("value"))
    )

    return {
        "id": candidate_id,
        "firstName": first_name,
        "lastName": last_name,
        "email": email,
    }

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

        employer_id = new_offer.get("employer_id") or new_offer.get("employerId")
        if not isinstance(employer_id, str) or not employer_id.strip():
            return jsonify({"error": "Missing employer_id in payload"}), 400

        new_offer["employer_id"] = employer_id.strip()
        new_offer["created_at"] = new_offer.get("created_at") or now_iso()
        new_offer["updated_at"] = now_iso()
        
        result = jobs_collection.insert_one(new_offer)
        return jsonify({"message": "Job offer created", "id": str(result.inserted_id)}), 201

@employers_bp.route('/applications/<employer_id>', methods=['GET'])
def get_employer_applications(employer_id):
    apps = list(applications_collection.find({"employer_id": employer_id}))
    for a in apps:
        a['_id'] = str(a['_id'])
    return jsonify(apps), 200


@employers_bp.route('/applications/<employer_id>/job/<job_id>', methods=['GET'])
def get_job_applicants(employer_id, job_id):
    job_doc = _resolve_job(job_id)
    if not job_doc:
        return jsonify({"error": "Job not found"}), 404

    job_employer_id = job_doc.get("employer_id")
    if str(job_employer_id) != str(employer_id):
        return jsonify({"error": "Job does not belong to employer"}), 403

    normalized_job_id = str(job_doc.get("_id")) if job_doc.get("_id") else str(job_id)
    app_docs = list(
        applications_collection
        .find({
            "employer_id": employer_id,
            "job_id": normalized_job_id,
        })
        .sort("created_at", -1)
    )

    candidate_ids = [
        app_doc.get("candidate_id")
        for app_doc in app_docs
        if isinstance(app_doc.get("candidate_id"), str)
    ]
    candidate_object_ids = []
    for candidate_id in candidate_ids:
        try:
            candidate_object_ids.append(ObjectId(candidate_id))
        except Exception:
            continue

    candidates_map = {}
    if candidate_object_ids:
        for candidate_doc in candidates_collection.find({"_id": {"$in": candidate_object_ids}}):
            candidates_map[str(candidate_doc.get("_id"))] = candidate_doc

    items = []
    for app_doc in app_docs:
        candidate_id = app_doc.get("candidate_id")
        candidate_doc = candidates_map.get(candidate_id)
        items.append({
            "applicationId": str(app_doc.get("_id")),
            "candidateId": candidate_id,
            "status": app_doc.get("status", "SENT"),
            "createdAt": app_doc.get("created_at"),
            "updatedAt": app_doc.get("updated_at"),
            "selectedDocuments": app_doc.get("selected_documents", []),
            "candidate": _safe_candidate_preview(candidate_doc, candidate_id),
        })

    return jsonify({
        "employerId": employer_id,
        "job": {
            "id": normalized_job_id,
            "title": job_doc.get("title"),
            "company": job_doc.get("company"),
            "location": job_doc.get("location"),
            "category": job_doc.get("category"),
        },
        "total": len(items),
        "items": items,
    }), 200


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


@employers_bp.route('/by-nip/<nip>', methods=['GET'])
def get_employer_by_nip(nip):
    """Fetch employer data by NIP number."""
    if not nip or not isinstance(nip, str) or not nip.strip():
        return jsonify({"error": "NIP is required"}), 400
    
    employer = employers_collection.find_one({"nip": nip.strip()})
    if not employer:
        return jsonify({"error": "Employer not found"}), 404
    
    employer['_id'] = str(employer.get('_id'))
    return jsonify(employer), 200


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