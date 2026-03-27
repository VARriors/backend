from datetime import datetime, timezone
import re

from bson.objectid import ObjectId


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
        return ObjectId(candidate_id)
    except Exception:
        return None


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
    if field == "doswiadczenia_zawodowe" and not isinstance(value, list):
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
    questionnaire = (candidate or {}).get("questionnaire")
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


def build_cv_gate_status(candidate_id, cv_doc, candidate_doc):
    questionnaire = get_or_create_questionnaire(candidate_doc) if candidate_doc else build_default_questionnaire()
    completion = questionnaire_completion(questionnaire)

    next_step = "add_cv"
    if cv_doc and not completion["is_complete"]:
        next_step = "complete_questionnaire"
    if cv_doc and completion["is_complete"]:
        next_step = "candidate_dashboard"

    return {
        "candidate_id": candidate_id,
        "has_cv": cv_doc is not None,
        "questionnaire_complete": completion["is_complete"],
        "missing_fields": completion["missing_fields"],
        "next_step": next_step,
    }
