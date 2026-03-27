from flask import Blueprint, jsonify, request

from app import db
from app.services.candidate_questionnaire_service import (
    SYSTEM_MOBYWATEL_FIELDS,
    SYSTEM_URZAD_PRACY_FIELDS,
    get_or_create_questionnaire,
    parse_object_id,
    questionnaire_completion,
    serialize_candidate,
)


candidates_bp = Blueprint('candidates', __name__)
candidates_collection = db['candidates']
cv_collection = db['cvs']


@candidates_bp.route('/', methods=['GET'])
def get_candidates():
    candidates = list(candidates_collection.find({}, {'_id': 0}).limit(20))
    return jsonify(candidates), 200


@candidates_bp.route('/profile/<candidate_id>', methods=['GET'])
def get_profile(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

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

    object_id = parse_object_id(candidate_id)
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
