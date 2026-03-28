from flask import Blueprint, jsonify
from app import db
from app.services.llm_match import evaluate_match_with_llm

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
        potential_jobs = list(jobs_collection.find({"required_skills": {"$in": candidate_skills}}).limit(10))
        if not potential_jobs:
             potential_jobs = list(jobs_collection.find({}).limit(10))
    else:
        potential_jobs = list(jobs_collection.find({}).limit(10))

    evaluated_jobs = []
    for job in potential_jobs:
        job['_id'] = str(job['_id'])
        if job.get('criteria'):
             evaluation_result = evaluate_match_with_llm(cv, job)
             job['match_score'] = evaluation_result['final_match_percentage']
             job['evaluation_details'] = evaluation_result
        else:
             job['match_score'] = 50 
             job['evaluation_details'] = {"message": "Oferta bez zdefiniowanych kryteriów."}
        evaluated_jobs.append(job)

    evaluated_jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)

    return jsonify({
        "candidate": candidate_id,
        "matches": evaluated_jobs
    }), 200

@matching_bp.route('/employer/<job_id>', methods=['GET'])
def get_matches_for_job(job_id):
    from bson.objectid import ObjectId
    try:
        job = jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        job = jobs_collection.find_one({"id": job_id}) 

    if not job:
         return jsonify({"message": "Nie znaleziono oferty pracy."}), 404

    potential_cvs = list(cv_collection.find({}).limit(15))
    
    evaluated_candidates = []
    for cv in potential_cvs:
        cv['_id'] = str(cv['_id'])
        
        if job.get('criteria'):
             evaluation_result = evaluate_match_with_llm(cv, job)
             cv['match_score'] = evaluation_result['final_match_percentage']
             cv['evaluation_details'] = evaluation_result
        else:
             cv['match_score'] = 50
             cv['evaluation_details'] = {"message": "Oferta bez zdefiniowanych kryteriów."}
             
        evaluated_candidates.append(cv)

    evaluated_candidates.sort(key=lambda x: x.get('match_score', 0), reverse=True)

    return jsonify({
        "job_id": job_id,
        "matches": evaluated_candidates
    }), 200
