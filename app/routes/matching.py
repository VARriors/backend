from flask import Blueprint, jsonify
from app import db
from app.services.llm_match import evaluate_match_with_llm
from bson.objectid import ObjectId

matching_bp = Blueprint('matching', __name__)
cv_collection = db['cvs']
jobs_collection = db['jobs']

@matching_bp.route('/candidate/<candidate_id>', methods=['GET'])
def get_matches_for_candidate(candidate_id):
    cv = cv_collection.find_one({"user_id": candidate_id})
    if not cv:
        return jsonify({"message": "Brak CV dla kandydata."}), 404

    potential_jobs = list(jobs_collection.find({}).limit(5))

    evaluated_jobs = []
    for job in potential_jobs:
        job['_id'] = str(job['_id'])
        evaluation = evaluate_match_with_llm(cv, job)
        job['smart_match'] = evaluation
        evaluated_jobs.append(job)

    evaluated_jobs.sort(key=lambda x: x['smart_match']['final_match_percentage'], reverse=True)

    return jsonify({
        "candidate": candidate_id,
        "matches": evaluated_jobs
    }), 200

@matching_bp.route('/employer/<job_id>', methods=['GET'])
def get_matches_for_job(job_id):
    try:
        job = jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        job = jobs_collection.find_one({"id": job_id}) 

    if not job:
         return jsonify({"message": "Nie znaleziono oferty pracy."}), 404

    potential_cvs = list(cv_collection.find({}).limit(5))
    
    evaluated_candidates = []
    for cv in potential_cvs:
        cv['_id'] = str(cv['_id'])
        evaluation = evaluate_match_with_llm(cv, job)
        cv['smart_match'] = evaluation
        evaluated_candidates.append(cv)

    evaluated_candidates.sort(key=lambda x: x['smart_match']['final_match_percentage'], reverse=True)

    return jsonify({
        "job_id": job_id,
        "matches": evaluated_candidates
    }), 200
        "required_skills": required_skills,
        "matched_candidates": matched_cvs,
    }), 200
