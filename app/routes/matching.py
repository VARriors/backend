from flask import Blueprint, jsonify
from app import db
from bson.objectid import ObjectId

matching_bp = Blueprint('matching', __name__)
cv_collection = db['cvs']
jobs_collection = db['jobs']

@matching_bp.route('/<candidate_id>', methods=['GET'])
def get_matches_for_candidate(candidate_id):
    cv = cv_collection.find_one({"user_id": candidate_id})
    if not cv:
        return jsonify({"message": "Brak CV dla kandydata. Utwórz by zacząć matching."}), 404

    candidate_skills = cv.get('skills', [])
    
    if candidate_skills:
        matched_jobs = list(jobs_collection.find({"required_skills": {"$in": candidate_skills}}).limit(10))
    else:
        matched_jobs = list(jobs_collection.find({}).limit(5))

    for job in matched_jobs:
        job['_id'] = str(job['_id'])
        
    return jsonify({
        "candidate": candidate_id,
        "matches": matched_jobs
    }), 200

@matching_bp.route('/employer/<job_id>', methods=['GET'])
def get_matches_for_job(job_id):
    try:
        object_id = ObjectId(job_id)
    except Exception:
        return jsonify({"error": "Invalid job ID"}), 400

    job_doc = jobs_collection.find_one({"_id": object_id})
    if not job_doc:
        return jsonify({"error": "Job not found"}), 404

    required_skills = job_doc.get("required_skills", [])
    if isinstance(required_skills, list) and required_skills:
        matched_cvs = list(
            cv_collection.find({"skills": {"$in": required_skills}}).limit(50)
        )
    else:
        matched_cvs = []

    for cv in matched_cvs:
        cv['_id'] = str(cv['_id'])

    return jsonify({
        "job_id": job_id,
        "required_skills": required_skills,
        "matched_candidates": matched_cvs,
    }), 200