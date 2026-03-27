from flask import Blueprint, jsonify, request
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

candidate_api_bp = Blueprint('candidate_api', __name__)
cv_collection = db['cvs']
candidates_collection = db['candidates']


def _unique_lower_strings(values):
    seen = set()
    output = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _derive_skills_from_questionnaire(questionnaire):
    fields = questionnaire.get("fields", {})
    raw = []
    for field_name in ["preferencje", "jezyki", "szkolenia", "kursy", "certyfikaty"]:
        field_payload = fields.get(field_name, {})
        value = field_payload.get("value") if isinstance(field_payload, dict) else None
        if isinstance(value, list):
            raw.extend(value)
    return _unique_lower_strings(raw)


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
    skills = _derive_skills_from_questionnaire(questionnaire)

    cv_doc = {
        "user_id": candidate_id,
        "source": "generated",
        "file_name": f"cv-generated-{candidate_id}.pdf",
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
