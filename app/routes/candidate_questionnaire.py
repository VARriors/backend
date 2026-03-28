from flask import Blueprint, jsonify, request

from app import db
from app.services.candidate_questionnaire_service import (
    FIELD_SOURCE_MAP,
    apply_updates,
    build_cv_gate_status,
    get_or_create_questionnaire,
    parse_object_id,
    questionnaire_completion,
)


candidate_questionnaire_bp = Blueprint('candidate_questionnaire', __name__)
candidates_collection = db['candidates']
cv_collection = db['cvs']


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>', methods=['GET'])
def get_questionnaire(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    completion = questionnaire_completion(questionnaire)

    return jsonify({
        "candidate_id": candidate_id,
        "questionnaire": questionnaire,
        "completion": completion,
        "field_sources": FIELD_SOURCE_MAP,
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/user-input', methods=['PUT'])
def upsert_user_questionnaire(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    payload = request.json or {}
    updates = payload.get("fields")
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "Missing 'fields' payload"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    errors = apply_updates(questionnaire, updates, "user")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    return jsonify({
        "message": "Questionnaire updated",
        "candidate_id": candidate_id,
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/mobywatel', methods=['PUT'])
def merge_mobywatel_data(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    payload = request.json or {}
    updates = payload.get("fields")
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "Missing 'fields' payload"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    errors = apply_updates(questionnaire, updates, "mobywatel")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    return jsonify({
        "message": "mObywatel data merged and verified",
        "candidate_id": candidate_id,
        "verified_fields": sorted(list(updates.keys())),
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/urzad-pracy', methods=['PUT'])
def merge_urzad_pracy_data(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    payload = request.json or {}
    updates = payload.get("fields")
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "Missing 'fields' payload"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    errors = apply_updates(questionnaire, updates, "urzad_pracy")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    return jsonify({
        "message": "Urzad Pracy data merged and verified",
        "candidate_id": candidate_id,
        "verified_fields": sorted(list(updates.keys())),
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/verification-summary', methods=['GET'])
def questionnaire_verification_summary(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    fields = questionnaire.get("fields", {})
    summary = {
        "verified": 0,
        "pending": 0,
        "unverified": 0,
        "rejected": 0,
        "total": len(fields),
    }

    per_field = {}
    for field_name, payload in fields.items():
        verification = payload.get("verification", {})
        status = verification.get("status", "unverified")
        if status in summary:
            summary[status] += 1
        per_field[field_name] = {
            "source": verification.get("source"),
            "status": status,
            "verified_by": verification.get("verified_by"),
            "verified_at": verification.get("verified_at"),
        }

    return jsonify({
        "candidate_id": candidate_id,
        "summary": summary,
        "per_field": per_field,
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/cv/status/<candidate_id>', methods=['GET'])
def get_cv_status(candidate_id):
    cv_doc = cv_collection.find_one({"user_id": candidate_id})

    object_id = parse_object_id(candidate_id)
    candidate = candidates_collection.find_one({"_id": object_id}) if object_id else None
    status = build_cv_gate_status(candidate_id, cv_doc, candidate)
    return jsonify(status), 200
