from flask import Blueprint, jsonify, request
from bson.objectid import ObjectId

from app import db
from app.services.candidate_questionnaire_service import (
    SYSTEM_MOBYWATEL_FIELDS,
    SYSTEM_URZAD_PRACY_FIELDS,
    FIELD_SOURCE_MAP,
    apply_updates,
    build_cv_gate_status,
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


@candidate_questionnaire_bp.route('/questionnaire/seed-demo', methods=['POST'])
def seed_demo_questionnaire():
    payload = request.json or {}

    first_name = payload.get("first_name") or "Jan"
    last_name = payload.get("last_name") or "Kowalski"
    create_cv = bool(payload.get("create_cv", True))

    candidate_doc = {
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    result = candidates_collection.insert_one(candidate_doc)
    candidate_id = str(result.inserted_id)
    candidate = candidates_collection.find_one({"_id": result.inserted_id})
    questionnaire = get_or_create_questionnaire(candidate)

    mobywatel_updates = {
        "imie": first_name,
        "nazwisko": last_name,
        "pesel": "90010112345",
        "dowod": "ABC123456",
        "niepelnosprawnosc": False,
    }
    user_updates = {
        "nr_telefonu": "+48500111222",
        "email": f"{str(first_name).lower()}.{str(last_name).lower()}@example.com",
        "preferencje": ["IT / Technologia", "Administracja"],
        "obszar_poszukiwan": "mazowieckie, Warszawa",
        "jezyki": ["Angielski (B2)", "Polski (natywny)"],
        "szkolenia": ["Kurs React"],
        "kursy": ["Kurs Python"],
        "certyfikaty": ["AWS Cloud Practitioner"],
        "aktywnosc_dodatkowa": ["Wolontariat"],
    }
    urzad_pracy_updates = {
        "doswiadczenia_zawodowe": [
            {
                "stanowisko": "Specjalista IT",
                "firma": "GovTech Solutions",
                "od": "2022-01",
                "do": "2024-12",
            }
        ]
    }

    errors = []
    errors.extend(apply_updates(questionnaire, mobywatel_updates, "mobywatel"))
    errors.extend(apply_updates(questionnaire, user_updates, "user"))
    errors.extend(apply_updates(questionnaire, urzad_pracy_updates, "urzad_pracy"))

    if errors:
        candidates_collection.delete_one({"_id": result.inserted_id})
        return jsonify({"error": "Seed validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": result.inserted_id},
        {"$set": {"questionnaire": questionnaire, "updated_at": now_iso()}},
    )

    completion = questionnaire_completion(questionnaire)

    if create_cv:
        cv_collection.update_one(
            {"user_id": candidate_id},
            {
                "$set": {
                    "user_id": candidate_id,
                    "source": "generated",
                    "file_name": f"cv-generated-{candidate_id}.pdf",
                    "generated_at": now_iso(),
                    "updated_at": now_iso(),
                    "questionnaire_complete": completion["is_complete"],
                    "questionnaire_missing_fields": completion["missing_fields"],
                    "verification_sources": {
                        "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
                        "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
                    },
                },
                "$setOnInsert": {"created_at": now_iso()},
            },
            upsert=True,
        )

    return jsonify({
        "message": "Demo candidate seeded",
        "candidate_id": candidate_id,
        "create_cv": create_cv,
        "completion": completion,
    }), 201


@candidate_questionnaire_bp.route('/cv/status/<candidate_id>', methods=['GET'])
def get_cv_status(candidate_id):
    cv_doc = cv_collection.find_one({"user_id": candidate_id})

    object_id = parse_object_id(candidate_id)
    candidate = candidates_collection.find_one({"_id": object_id}) if object_id else None
    status = build_cv_gate_status(candidate_id, cv_doc, candidate)
    return jsonify(status), 200


@candidate_questionnaire_bp.route('/questionnaire/seed-demo', methods=['POST'])
def seed_demo_candidate():
    data = request.json or {}
    first_name = data.get("first_name", "Jan")
    last_name = data.get("last_name", "Kowalski")
    candidate_id = "65f1a2b3c4d5e6f7a8b9c0d1"
    object_id = ObjectId(candidate_id)

    # Clean existing
    candidates_collection.delete_one({"_id": object_id})
    cv_collection.delete_one({"user_id": candidate_id})

    questionnaire = get_or_create_questionnaire(None)
    questionnaire["fields"]["imie"]["value"] = first_name
    questionnaire["fields"]["nazwisko"]["value"] = last_name

    candidate = {
        "_id": object_id,
        "first_name": first_name,
        "last_name": last_name,
        "email": f"{first_name.lower()}.{last_name.lower()}@example.com",
        "questionnaire": questionnaire,
        "created_at": now_iso()
    }

    candidates_collection.insert_one(candidate)

    if data.get("create_cv"):
        cv_data = {
            "user_id": candidate_id,
            "has_cv": True,
            "created_at": now_iso()
        }
        cv_collection.insert_one(cv_data)

    return jsonify({
        "message": "Demo candidate seeded",
        "candidate_id": candidate_id,
        "questionnaire": questionnaire
    }), 201
