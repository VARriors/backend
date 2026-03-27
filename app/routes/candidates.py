from flask import Blueprint, jsonify, request
from app import db
from bson.objectid import ObjectId

candidates_bp = Blueprint('candidates', __name__)
candidates_collection = db['candidates']
cv_collection = db['cvs']

@candidates_bp.route('/', methods=['GET'])
def get_candidates():
    candidates = list(candidates_collection.find({}, {'_id': 0}).limit(20))
    return jsonify(candidates), 200

@candidates_bp.route('/profile/<candidate_id>', methods=['GET'])
def get_profile(candidate_id):
    try:
        user = candidates_collection.find_one({"_id": ObjectId(candidate_id)})
        if not user:
            return jsonify({"error": "Candidate not found"}), 404
        user['_id'] = str(user['_id'])
        return jsonify(user), 200
    except Exception as e:
        return jsonify({"error": "Invalid ID"}), 400

@candidates_bp.route('/cv', methods=['POST'])
def upload_cv():
    data = request.json
    if not data or 'user_id' not in data:
        return jsonify({"error": "brakuje user_id"}), 400

    result = cv_collection.insert_one(data)
    return jsonify({"message": "CV utworzone", "cv_id": str(result.inserted_id)}), 201