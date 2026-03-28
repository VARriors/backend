from bson.objectid import ObjectId
from flask import Blueprint, jsonify, request

from app import db
from app.services.llm_match import evaluate_match_with_llm


matching_bp = Blueprint('matching', __name__)
cv_collection = db['cvs']
jobs_collection = db['jobs']
applications_collection = db['applications']
candidates_collection = db['candidates']


def _to_positive_int(value, default_value=10, max_value=50):
    try:
        parsed = int(value)
        if parsed <= 0:
            return default_value
        if parsed > max_value:
            return max_value
        return parsed
    except (TypeError, ValueError):
        return default_value


def _resolve_job(job_id):
    try:
        return jobs_collection.find_one({"_id": ObjectId(job_id)})
    except Exception:
        return jobs_collection.find_one({"id": job_id})


def _job_payload(job_doc):
    return {
        "id": str(job_doc.get("_id")) if job_doc.get("_id") else job_doc.get("id"),
        "title": job_doc.get("title"),
        "company": job_doc.get("company"),
        "location": job_doc.get("location"),
        "category": job_doc.get("category"),
        "requiredSkills": job_doc.get("required_skills", []),
    }


def _candidate_payload(candidate_id, cv_doc):
    candidate_doc = None
    try:
        candidate_doc = candidates_collection.find_one({"_id": ObjectId(candidate_id)})
    except Exception:
        candidate_doc = None

    questionnaire_fields = ((candidate_doc or {}).get("questionnaire") or {}).get("fields") or {}
    return {
        "id": candidate_id,
        "firstName": (candidate_doc or {}).get("first_name") or (questionnaire_fields.get("imie") or {}).get("value"),
        "lastName": (candidate_doc or {}).get("last_name") or (questionnaire_fields.get("nazwisko") or {}).get("value"),
        "email": (candidate_doc or {}).get("email") or (questionnaire_fields.get("email") or {}).get("value"),
        "skills": cv_doc.get("skills") or ((cv_doc.get("extracted_data") or {}).get("skills")) or [],
    }


@matching_bp.route('/candidate/<candidate_id>', methods=['GET'])
def get_matches_for_candidate(candidate_id):
    cv_doc = cv_collection.find_one({"user_id": candidate_id})
    if not cv_doc:
        return jsonify({"message": "Candidate CV not found"}), 404

    limit = _to_positive_int(request.args.get("limit"), default_value=10)
    potential_jobs = list(jobs_collection.find({}).limit(limit))
    normalized_applied_job_ids = set()
    for app_doc in applications_collection.find({"candidate_id": candidate_id}, {"job_id": 1}):
        job_id = app_doc.get("job_id")
        if isinstance(job_id, str):
            normalized_applied_job_ids.add(job_id)

    evaluated_jobs = []
    for job_doc in potential_jobs:
        job_id = str(job_doc.get("_id")) if job_doc.get("_id") else str(job_doc.get("id"))
        evaluation = evaluate_match_with_llm(cv_doc, job_doc)
        evaluated_jobs.append({
            "job": _job_payload(job_doc),
            "smartMatch": evaluation,
            "alreadyApplied": job_id in normalized_applied_job_ids,
        })

    evaluated_jobs.sort(
        key=lambda item: item.get("smartMatch", {}).get("final_match_percentage", 0),
        reverse=True,
    )

    return jsonify({
        "candidateId": candidate_id,
        "total": len(evaluated_jobs),
        "matches": evaluated_jobs,
    }), 200


@matching_bp.route('/employer/<job_id>', methods=['GET'])
def get_matches_for_job(job_id):
    job_doc = _resolve_job(job_id)
    if not job_doc:
        return jsonify({"message": "Job not found"}), 404

    limit = _to_positive_int(request.args.get("limit"), default_value=10)
    normalized_job_id = str(job_doc.get("_id")) if job_doc.get("_id") else str(job_id)

    app_docs = list(
        applications_collection
        .find({"job_id": normalized_job_id})
        .sort("created_at", -1)
    )

    applicant_ids = []
    for app_doc in app_docs:
        candidate_id = app_doc.get("candidate_id")
        if isinstance(candidate_id, str) and candidate_id not in applicant_ids:
            applicant_ids.append(candidate_id)

    candidate_cv_docs = []
    if applicant_ids:
        candidate_cv_docs.extend(list(cv_collection.find({"user_id": {"$in": applicant_ids}}).limit(limit)))

    if len(candidate_cv_docs) < limit:
        existing_ids = [cv.get("user_id") for cv in candidate_cv_docs]
        cursor = cv_collection.find({"user_id": {"$nin": existing_ids}}).limit(limit - len(candidate_cv_docs))
        candidate_cv_docs.extend(list(cursor))

    applications_by_candidate = {
        app.get("candidate_id"): app
        for app in app_docs
        if isinstance(app.get("candidate_id"), str)
    }

    evaluated_candidates = []
    for cv_doc in candidate_cv_docs:
        candidate_id = cv_doc.get("user_id")
        if not isinstance(candidate_id, str):
            continue

        evaluation = evaluate_match_with_llm(cv_doc, job_doc)
        app_doc = applications_by_candidate.get(candidate_id)

        evaluated_candidates.append({
            "candidate": _candidate_payload(candidate_id, cv_doc),
            "smartMatch": evaluation,
            "application": {
                "applicationId": str(app_doc.get("_id")) if app_doc else None,
                "status": app_doc.get("status") if app_doc else None,
                "createdAt": app_doc.get("created_at") if app_doc else None,
            } if app_doc else None,
        })

    evaluated_candidates.sort(
        key=lambda item: item.get("smartMatch", {}).get("final_match_percentage", 0),
        reverse=True,
    )

    return jsonify({
        "job": _job_payload(job_doc),
        "total": len(evaluated_candidates),
        "applicantsCount": len(applicant_ids),
        "matches": evaluated_candidates,
    }), 200
