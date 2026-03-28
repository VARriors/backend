from flask import Blueprint, jsonify, request
from bson.objectid import ObjectId

from app import db
from app.services.candidate_questionnaire_service import (
    SYSTEM_MOBYWATEL_FIELDS,
    SYSTEM_URZAD_PRACY_FIELDS,
    apply_updates,
    build_cv_gate_status,
    get_or_create_questionnaire,
    now_iso,
    parse_object_id,
    questionnaire_completion,
)
from app.services.ledger_service import create_application

candidate_api_bp = Blueprint('candidate_api', __name__)
cv_collection = db['cvs']
candidates_collection = db['candidates']
jobs_collection = db['jobs']
applications_collection = db['applications']


def _extract_candidate_id(payload=None):
    payload = payload or {}
    return (
        request.args.get('candidateId')
        or request.headers.get('X-Candidate-Id')
        or payload.get('candidateId')
        or payload.get('candidate_id')
        or payload.get('user_id')
    )


def _get_candidate_doc(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return None
    return candidates_collection.find_one({"_id": object_id})


def _sync_cv_questionnaire_state(candidate_id, questionnaire):
    completion = questionnaire_completion(questionnaire)
    cv_collection.update_one(
        {"user_id": candidate_id},
        {
            "$set": {
                "questionnaire_complete": completion["is_complete"],
                "questionnaire_missing_fields": completion["missing_fields"],
                "updated_at": now_iso(),
            }
        },
    )


def _resolve_job(job_id):
    if not isinstance(job_id, str) or not job_id.strip():
        return None

    clean_job_id = job_id.strip()
    try:
        return jobs_collection.find_one({"_id": ObjectId(clean_job_id)})
    except Exception:
        return jobs_collection.find_one({"id": clean_job_id})


def _normalize_job_id(job_doc, fallback_job_id):
    if job_doc and "_id" in job_doc:
        return str(job_doc["_id"])
    return fallback_job_id

@candidate_api_bp.route('/cv/status', methods=['GET'])
def get_candidate_cv_status():
    """
    Returns whether the candidate already has a CV in the system.
    Candidate ID can be provided via:
    - query param: candidateId
    - header: X-Candidate-Id
    """
    candidate_id = _extract_candidate_id()

    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param or X-Candidate-Id header)"
        }), 400

    cv_doc = cv_collection.find_one(
        {"user_id": candidate_id},
        {
            "_id": 1,
            "source": 1,
            "file_name": 1,
            "updated_at": 1,
            "created_at": 1,
        },
    )

    candidate_doc = _get_candidate_doc(candidate_id)
    status = build_cv_gate_status(candidate_id, cv_doc, candidate_doc)

    cv_payload = None
    if cv_doc:
        cv_payload = {
            "id": str(cv_doc.get('_id')),
            "source": cv_doc.get('source', 'uploaded'),
            "fileName": cv_doc.get('file_name'),
            "updatedAt": cv_doc.get('updated_at') or cv_doc.get('created_at'),
        }

    return jsonify({
        "candidateId": status["candidate_id"],
        "hasCv": status["has_cv"],
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
        "cv": cv_payload,
    }), 200


@candidate_api_bp.route('/cv/generate', methods=['POST'])
def generate_candidate_cv():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate_doc)
    completion = questionnaire_completion(questionnaire)
    preferences = questionnaire.get("fields", {}).get("preferencje", {}).get("value") or []

    skills = payload.get("skills")
    if not isinstance(skills, list) or not all(isinstance(item, str) for item in skills):
        skills = [str(item).lower() for item in preferences if isinstance(item, str)]

    cv_doc = {
        "user_id": candidate_id,
        "source": "generated",
        "file_name": "cv-government-generated.pdf",
        "generated_at": now_iso(),
        "updated_at": now_iso(),
        "skills": skills,
        "questionnaire_complete": completion["is_complete"],
        "questionnaire_missing_fields": completion["missing_fields"],
        "verification_sources": {
            "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
            "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
        },
    }

    existing = cv_collection.find_one({"user_id": candidate_id}, {"_id": 1})
    result = cv_collection.update_one(
        {"user_id": candidate_id},
        {
            "$set": cv_doc,
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )

    cv_id = str(result.upserted_id) if result.upserted_id else str(existing.get("_id"))
    status = build_cv_gate_status(candidate_id, cv_doc, candidate_doc)

    return jsonify({
        "message": "CV generated from verified profile data",
        "candidateId": candidate_id,
        "cvId": cv_id,
        "hasCv": status["has_cv"],
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
    }), 201 if result.upserted_id else 200


@candidate_api_bp.route('/cv/upload', methods=['POST'])
def upload_candidate_cv_pdf():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    file_name = payload.get("fileName") or payload.get("file_name")
    if not isinstance(file_name, str) or not file_name.lower().endswith('.pdf'):
        return jsonify({"error": "fileName is required and must be a PDF filename"}), 400

    mime_type = payload.get("mimeType") or payload.get("mime_type")
    if mime_type and mime_type != "application/pdf":
        return jsonify({"error": "Only application/pdf is supported"}), 400

    questionnaire = get_or_create_questionnaire(candidate_doc)
    completion = questionnaire_completion(questionnaire)

    cv_doc = {
        "user_id": candidate_id,
        "source": "uploaded",
        "file_name": file_name,
        "file_url": payload.get("fileUrl") or payload.get("file_url"),
        "mime_type": "application/pdf",
        "file_size_bytes": payload.get("fileSizeBytes") or payload.get("file_size_bytes"),
        "updated_at": now_iso(),
        "questionnaire_complete": completion["is_complete"],
        "questionnaire_missing_fields": completion["missing_fields"],
        "verification_sources": {
            "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
            "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
        },
    }

    existing = cv_collection.find_one({"user_id": candidate_id}, {"_id": 1})
    result = cv_collection.update_one(
        {"user_id": candidate_id},
        {
            "$set": cv_doc,
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )

    cv_id = str(result.upserted_id) if result.upserted_id else str(existing.get("_id"))
    status = build_cv_gate_status(candidate_id, cv_doc, candidate_doc)

    return jsonify({
        "message": "CV PDF uploaded",
        "candidateId": candidate_id,
        "cvId": cv_id,
        "hasCv": status["has_cv"],
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
    }), 201 if result.upserted_id else 200


@candidate_api_bp.route('/preferences', methods=['PUT'])
def update_candidate_preferences():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    categories = payload.get("categories")
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        return jsonify({"error": "categories must be an array of strings"}), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate_doc)
    user_updates = {
        "preferencje": categories,
    }

    job_area = payload.get("jobArea")
    if isinstance(job_area, str) and job_area.strip():
        user_updates["obszar_poszukiwan"] = job_area.strip()

    errors = apply_updates(questionnaire, user_updates, "user")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    object_id = parse_object_id(candidate_id)
    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    _sync_cv_questionnaire_state(candidate_id, questionnaire)
    cv_doc = cv_collection.find_one({"user_id": candidate_id}, {"_id": 1})
    status = build_cv_gate_status(candidate_id, cv_doc, {"questionnaire": questionnaire})

    return jsonify({
        "message": "Candidate preferences saved",
        "candidateId": candidate_id,
        "categories": categories,
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
    }), 200


@candidate_api_bp.route('/apply', methods=['POST'])
def apply_to_job_offer():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    job_id = payload.get("job_id") or payload.get("jobId")
    job_doc = _resolve_job(job_id)
    if not job_doc:
        return jsonify({"error": "Job not found"}), 404

    normalized_job_id = _normalize_job_id(job_doc, job_id)
    employer_id = payload.get("employer_id") or payload.get("employerId") or job_doc.get("employer_id")
    if not employer_id:
        return jsonify({"error": "employer_id is required (payload or job.employer_id)"}), 400

    existing = applications_collection.find_one({
        "candidate_id": candidate_id,
        "job_id": normalized_job_id,
        "employer_id": employer_id,
    })

    if existing:
        if not existing.get("ledger_application_ref"):
            ledger_result = create_application(
                candidate_id=candidate_id,
                employer_id=employer_id,
                job_id=normalized_job_id,
                metadata={"origin": "candidate_apply_link"},
            )
            applications_collection.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "status": "SENT",
                        "updated_at": now_iso(),
                        "ledger_application_ref": ledger_result["application_ref"],
                        "ledger_application_commitment": ledger_result["application_commitment"],
                        "ledger_latest_status": "SENT",
                        "ledger_claim_token": ledger_result["claim_token"],
                    }
                },
            )
            existing["ledger_application_ref"] = ledger_result["application_ref"]
            existing["ledger_application_commitment"] = ledger_result["application_commitment"]
            existing["ledger_claim_token"] = ledger_result["claim_token"]
            existing["status"] = "SENT"

        return jsonify({
            "message": "Application already exists",
            "applicationId": str(existing["_id"]),
            "candidateId": candidate_id,
            "employerId": employer_id,
            "jobId": normalized_job_id,
            "status": existing.get("status", "SENT"),
            "ledger": {
                "applicationRef": existing.get("ledger_application_ref"),
                "applicationCommitment": existing.get("ledger_application_commitment"),
                "claimToken": existing.get("ledger_claim_token"),
            },
        }), 200

    ledger_result = create_application(
        candidate_id=candidate_id,
        employer_id=employer_id,
        job_id=normalized_job_id,
        metadata={
            "origin": "candidate_apply",
            "job_title": job_doc.get("title"),
        },
    )

    application_doc = {
        "candidate_id": candidate_id,
        "employer_id": employer_id,
        "job_id": normalized_job_id,
        "status": "SENT",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "ledger_application_ref": ledger_result["application_ref"],
        "ledger_application_commitment": ledger_result["application_commitment"],
        "ledger_latest_status": "SENT",
        "ledger_claim_token": ledger_result["claim_token"],
    }

    result = applications_collection.insert_one(application_doc)
    return jsonify({
        "message": "Application created",
        "applicationId": str(result.inserted_id),
        "candidateId": candidate_id,
        "employerId": employer_id,
        "jobId": normalized_job_id,
        "status": "SENT",
        "ledger": {
            "applicationRef": ledger_result["application_ref"],
            "applicationCommitment": ledger_result["application_commitment"],
            "claimToken": ledger_result["claim_token"],
        },
    }), 201
