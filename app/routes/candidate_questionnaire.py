from bson.objectid import ObjectId
from flask import Blueprint, jsonify, request

from app import db
from app.services.candidate_questionnaire_service import (
    FIELD_SOURCE_MAP,
    SYSTEM_MOBYWATEL_FIELDS,
    SYSTEM_URZAD_PRACY_FIELDS,
    apply_updates,
    build_cv_gate_status,
    build_default_questionnaire,
    get_or_create_questionnaire,
    now_iso,
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


@candidate_questionnaire_bp.route('/questionnaire/seed-demo', methods=['POST'])
def seed_demo_questionnaire():
    payload = request.json or {}
    first_name = payload.get("first_name", "Jan")
    last_name = payload.get("last_name", "Kowalski")
    create_cv = bool(payload.get("create_cv", True))

    candidate = {
        "firstName": first_name,
        "lastName": last_name,
        "hasSanepid": False,
        "cleanCriminalRecord": False,
        "hasDrivingLicense": False,
        "questionnaire": build_default_questionnaire(),
        "created_at": now_iso(),
    }

    result = candidates_collection.insert_one(candidate)
    candidate_id = str(result.inserted_id)

    mobywatel_fields = {
        "imie": first_name,
        "nazwisko": last_name,
        "pesel": "90010112345",
        "dowod": "ABC123456",
        "niepelnosprawnosc": False,
    }
    urzad_pracy_fields = {
        "doswiadczenia_zawodowe": [
            {
                "stanowisko": "Mlodszy specjalista ds. obslugi klienta",
                "firma": "Urzad Miasta",
                "od": "2021-01",
                "do": "2023-08",
            }
        ]
    }
    user_fields = {
        "nr_telefonu": "+48500111222",
        "email": "jan.kowalski@example.com",
        "preferencje": ["IT", "Administracja"],
        "obszar_poszukiwan": "Warszawa i okolice",
        "jezyki": ["polski", "angielski"],
        "szkolenia": ["Szkolenie RODO"],
        "kursy": ["Kurs Excel zaawansowany"],
        "certyfikaty": ["ECDL"],
        "aktywnosc_dodatkowa": "Wolontariat lokalny",
    }

    candidate_record = candidates_collection.find_one({"_id": ObjectId(candidate_id)})
    questionnaire = get_or_create_questionnaire(candidate_record)
    apply_updates(questionnaire, mobywatel_fields, "mobywatel")
    apply_updates(questionnaire, urzad_pracy_fields, "urzad_pracy")
    apply_updates(questionnaire, user_fields, "user")

    candidates_collection.update_one(
        {"_id": ObjectId(candidate_id)},
        {"$set": {"questionnaire": questionnaire}},
    )

    cv_id = None
    if create_cv:
        cv_payload = {
            "user_id": candidate_id,
            "skills": ["excel", "obsluga klienta", "react"],
            "questionnaire_complete": questionnaire_completion(questionnaire)["is_complete"],
            "questionnaire_missing_fields": questionnaire_completion(questionnaire)["missing_fields"],
            "verification_sources": {
                "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
                "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
            },
        }
        cv_result = cv_collection.insert_one(cv_payload)
        cv_id = str(cv_result.inserted_id)

    return jsonify({
        "message": "Demo candidate seeded",
        "candidate_id": candidate_id,
        "cv_id": cv_id,
        "completion": questionnaire_completion(questionnaire),
    }), 201
