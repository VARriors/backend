from flask import Blueprint, jsonify, request
from app import db
from bson.objectid import ObjectId
from datetime import datetime, timezone
import re

candidates_bp = Blueprint('candidates', __name__)
candidates_collection = db['candidates']
cv_collection = db['cvs']

FIELD_SOURCE_MAP = {
    "imie": "mobywatel",
    "nazwisko": "mobywatel",
    "pesel": "mobywatel",
    "dowod": "mobywatel",
    "niepelnosprawnosc": "mobywatel",
    "doswiadczenia_zawodowe": "urzad_pracy",
    "nr_telefonu": "user",
    "email": "user",
    "preferencje": "user",
    "obszar_poszukiwan": "user",
    "jezyki": "user",
    "szkolenia": "user",
    "kursy": "user",
    "certyfikaty": "user",
    "aktywnosc_dodatkowa": "user",
}

SYSTEM_MOBYWATEL_FIELDS = [
    "imie",
    "nazwisko",
    "pesel",
    "dowod",
    "niepelnosprawnosc",
]

SYSTEM_URZAD_PRACY_FIELDS = ["doswiadczenia_zawodowe"]

USER_FIELDS = [
    "nr_telefonu",
    "email",
    "preferencje",
    "obszar_poszukiwan",
    "jezyki",
    "szkolenia",
    "kursy",
    "certyfikaty",
    "aktywnosc_dodatkowa",
]

REQUIRED_QUESTIONNAIRE_FIELDS = [
    "imie",
    "nazwisko",
    "pesel",
    "nr_telefonu",
    "email",
    "preferencje",
    "obszar_poszukiwan",
    "doswiadczenia_zawodowe",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_object_id(candidate_id):
    try:
        return ObjectId(candidate_id), None
    except Exception:
        return None, (jsonify({"error": "Invalid ID"}), 400)


def validate_email(value):
    return isinstance(value, str) and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None


def validate_phone(value):
    if not isinstance(value, str):
        return False
    compact = re.sub(r"\s+", "", value)
    return re.fullmatch(r"(\+48)?\d{9}", compact) is not None


def validate_pesel(value):
    return isinstance(value, str) and re.fullmatch(r"\d{11}", value) is not None


def validate_field_payload(field, value):
    if field == "email" and not validate_email(value):
        return "Invalid email format"
    if field == "nr_telefonu" and not validate_phone(value):
        return "Invalid phone format, expected +48XXXXXXXXX or 9 digits"
    if field == "pesel" and not validate_pesel(value):
        return "Invalid PESEL format, expected 11 digits"
    if field in ["preferencje", "jezyki", "szkolenia", "kursy", "certyfikaty"]:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return f"Field '{field}' must be an array of strings"
    if field == "doswiadczenia_zawodowe":
        if not isinstance(value, list):
            return "Field 'doswiadczenia_zawodowe' must be an array"
    return None


def default_verification_for_source(source):
    if source == "user":
        return {
            "source": "user",
            "status": "unverified",
            "verified_by": None,
            "verified_at": None,
            "note": None,
        }

    return {
        "source": source,
        "status": "pending",
        "verified_by": None,
        "verified_at": None,
        "note": None,
    }


def build_default_questionnaire():
    fields = {}
    for field_name, source in FIELD_SOURCE_MAP.items():
        fields[field_name] = {
            "value": None,
            "verification": default_verification_for_source(source),
        }

    return {
        "fields": fields,
        "updated_at": now_iso(),
    }


def get_or_create_questionnaire(candidate):
    questionnaire = candidate.get("questionnaire")
    if isinstance(questionnaire, dict) and isinstance(questionnaire.get("fields"), dict):
        return questionnaire

    return build_default_questionnaire()


def apply_updates(questionnaire, updates, authority):
    fields = questionnaire["fields"]
    errors = []

    for field_name, field_value in updates.items():
        if field_name not in FIELD_SOURCE_MAP:
            errors.append(f"Unknown field '{field_name}'")
            continue

        expected_source = FIELD_SOURCE_MAP[field_name]
        if authority != expected_source:
            errors.append(
                f"Field '{field_name}' belongs to source '{expected_source}', not '{authority}'"
            )
            continue

        validation_error = validate_field_payload(field_name, field_value)
        if validation_error:
            errors.append(validation_error)
            continue

        existing = fields.get(field_name, {
            "value": None,
            "verification": default_verification_for_source(expected_source),
        })
        existing["value"] = field_value

        if authority in ["mobywatel", "urzad_pracy"]:
            existing["verification"] = {
                "source": authority,
                "status": "verified",
                "verified_by": authority,
                "verified_at": now_iso(),
                "note": "Auto-verified by authority payload",
            }
        else:
            existing["verification"] = {
                "source": "user",
                "status": "unverified",
                "verified_by": None,
                "verified_at": None,
                "note": None,
            }

        fields[field_name] = existing

    questionnaire["updated_at"] = now_iso()
    return errors


def questionnaire_completion(questionnaire):
    fields = questionnaire.get("fields", {})
    missing = []
    for field_name in REQUIRED_QUESTIONNAIRE_FIELDS:
        entry = fields.get(field_name)
        value = entry.get("value") if isinstance(entry, dict) else None
        if value is None or value == "" or value == []:
            missing.append(field_name)
    return {
        "is_complete": len(missing) == 0,
        "missing_fields": missing,
    }


def serialize_candidate(candidate):
    if candidate and "_id" in candidate:
        candidate["_id"] = str(candidate["_id"])
    return candidate

@candidates_bp.route('/', methods=['GET'])
def get_candidates():
    candidates = list(candidates_collection.find({}, {'_id': 0}).limit(20))
    return jsonify(candidates), 200

@candidates_bp.route('/profile/<candidate_id>', methods=['GET'])
def get_profile(candidate_id):
    object_id, error_response = parse_object_id(candidate_id)
    if error_response:
        return error_response

    user = candidates_collection.find_one({"_id": object_id})
    if not user:
        return jsonify({"error": "Candidate not found"}), 404

    user = serialize_candidate(user)
    return jsonify(user), 200

@candidates_bp.route('/cv', methods=['POST'])
def upload_cv():
    data = request.json
    if not data or 'user_id' not in data:
        return jsonify({"error": "brakuje user_id"}), 400

    candidate_id = data.get("user_id")
    cv_exists = cv_collection.find_one({"user_id": candidate_id})
    if cv_exists:
        return jsonify({"error": "CV for this user already exists"}), 409

    object_id, _ = parse_object_id(candidate_id)
    candidate = candidates_collection.find_one({"_id": object_id}) if object_id else None

    if candidate:
        questionnaire = get_or_create_questionnaire(candidate)
        completion = questionnaire_completion(questionnaire)
        data["questionnaire_complete"] = completion["is_complete"]
        data["questionnaire_missing_fields"] = completion["missing_fields"]
        data["verification_sources"] = {
            "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
            "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
        }

    result = cv_collection.insert_one(data)
    return jsonify({"message": "CV utworzone", "cv_id": str(result.inserted_id)}), 201


@candidates_bp.route('/questionnaire/<candidate_id>', methods=['GET'])
def get_questionnaire(candidate_id):
    object_id, error_response = parse_object_id(candidate_id)
    if error_response:
        return error_response

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


@candidates_bp.route('/questionnaire/<candidate_id>/user-input', methods=['PUT'])
def upsert_user_questionnaire(candidate_id):
    object_id, error_response = parse_object_id(candidate_id)
    if error_response:
        return error_response

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
        {"$set": {"questionnaire": questionnaire}}
    )

    return jsonify({
        "message": "Questionnaire updated",
        "candidate_id": candidate_id,
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidates_bp.route('/questionnaire/<candidate_id>/mobywatel', methods=['PUT'])
def merge_mobywatel_data(candidate_id):
    object_id, error_response = parse_object_id(candidate_id)
    if error_response:
        return error_response

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
        {"$set": {"questionnaire": questionnaire}}
    )

    return jsonify({
        "message": "mObywatel data merged and verified",
        "candidate_id": candidate_id,
        "verified_fields": sorted(list(updates.keys())),
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidates_bp.route('/questionnaire/<candidate_id>/urzad-pracy', methods=['PUT'])
def merge_urzad_pracy_data(candidate_id):
    object_id, error_response = parse_object_id(candidate_id)
    if error_response:
        return error_response

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
        {"$set": {"questionnaire": questionnaire}}
    )

    return jsonify({
        "message": "Urzad Pracy data merged and verified",
        "candidate_id": candidate_id,
        "verified_fields": sorted(list(updates.keys())),
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidates_bp.route('/questionnaire/<candidate_id>/verification-summary', methods=['GET'])
def questionnaire_verification_summary(candidate_id):
    object_id, error_response = parse_object_id(candidate_id)
    if error_response:
        return error_response

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


@candidates_bp.route('/cv/status/<candidate_id>', methods=['GET'])
def get_cv_status(candidate_id):
    cv = cv_collection.find_one({"user_id": candidate_id})

    object_id, _ = parse_object_id(candidate_id)
    candidate = candidates_collection.find_one({"_id": object_id}) if object_id else None
    questionnaire = get_or_create_questionnaire(candidate) if candidate else build_default_questionnaire()
    completion = questionnaire_completion(questionnaire)

    next_step = "add_cv"
    if cv and not completion["is_complete"]:
        next_step = "complete_questionnaire"
    if cv and completion["is_complete"]:
        next_step = "candidate_dashboard"

    return jsonify({
        "candidate_id": candidate_id,
        "has_cv": cv is not None,
        "questionnaire_complete": completion["is_complete"],
        "missing_fields": completion["missing_fields"],
        "next_step": next_step,
    }), 200


@candidates_bp.route('/questionnaire/seed-demo', methods=['POST'])
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
        {"$set": {"questionnaire": questionnaire}}
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