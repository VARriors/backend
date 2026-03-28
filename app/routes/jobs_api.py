from flask import Blueprint, jsonify, request
from bson.errors import InvalidId
from bson.objectid import ObjectId

from app import db
from app.services.job_requirements_service import (
    get_job_cv_requirements,
    validate_cv_requirement_for_application,
)


jobs_api_bp = Blueprint('jobs_api', __name__)
jobs_collection = db['jobs']


def _to_positive_int(value, default_value, max_value=None):
    try:
        parsed = int(value)
        if parsed <= 0:
            return default_value
        if max_value is not None and parsed > max_value:
            return max_value
        return parsed
    except (TypeError, ValueError):
        return default_value


def _serialize_job(job_doc):
    return {
        "id": str(job_doc.get("_id")),
        "title": job_doc.get("title"),
        "company": job_doc.get("company"),
        "location": job_doc.get("location"),
        "category": job_doc.get("category"),
        "description": job_doc.get("description"),
        "salaryRange": job_doc.get("salary_range") or job_doc.get("salaryRange"),
        "requiredSkills": job_doc.get("required_skills", []),
        "requiredBadges": job_doc.get("required_badges", []),
        "employmentType": job_doc.get("employment_type") or job_doc.get("employmentType"),
        "workTime": job_doc.get("work_time") or job_doc.get("workTime"),
        "workMode": job_doc.get("work_mode") or job_doc.get("workMode"),
        "positionLevel": job_doc.get("position_level") or job_doc.get("positionLevel"),
        "minExperience": job_doc.get("min_experience") or job_doc.get("minExperience"),
        "minEducation": job_doc.get("min_education") or job_doc.get("minEducation"),
        "languages": job_doc.get("languages", []),
        "expectations": job_doc.get("expectations"),
        "tags": job_doc.get("tags", []),
        "benefits": job_doc.get("benefits", []),
        "responsibilities": job_doc.get("responsibilities", []),
        "applicationDeadline": job_doc.get("application_deadline") or job_doc.get("applicationDeadline"),
        "requiresCv": job_doc.get("requires_cv", False),
        "cvRequiredReason": job_doc.get("cv_required_reason"),
        "createdAt": job_doc.get("created_at"),
        "updatedAt": job_doc.get("updated_at"),
    }


@jobs_api_bp.route('/jobs', methods=['GET', 'POST'])
def list_jobs():
    """
    Public jobs listing endpoint for candidate job search.
    Supported query params: q, category, location, company, page, limit.
    """
    if request.method == 'POST':
        new_offer = request.json
        if not new_offer or 'title' not in new_offer:
            return jsonify({"error": "Missing title in payload"}), 400
            
        result = jobs_collection.insert_one(new_offer)
        return jsonify({"message": "Job offer created", "id": str(result.inserted_id)}), 201
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    location = request.args.get('location', '').strip()
    company = request.args.get('company', '').strip()

    page = _to_positive_int(request.args.get('page'), default_value=1)
    limit = _to_positive_int(request.args.get('limit'), default_value=20, max_value=100)
    skip = (page - 1) * limit

    mongo_filter = {}
    if q:
        mongo_filter["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"company": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]
    if category:
        mongo_filter["category"] = {"$regex": f"^{category}$", "$options": "i"}
    if location:
        mongo_filter["location"] = {"$regex": location, "$options": "i"}
    if company:
        mongo_filter["company"] = {"$regex": company, "$options": "i"}

    total = jobs_collection.count_documents(mongo_filter)
    cursor = jobs_collection.find(mongo_filter).sort("_id", -1).skip(skip).limit(limit)
    jobs = [_serialize_job(job_doc) for job_doc in cursor]

    return jsonify({
        "items": jobs,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit,
        },
        "filters": {
            "q": q or None,
            "category": category or None,
            "location": location or None,
            "company": company or None,
        },
    }), 200

# @jobs_api_bp.route('/jobs', methods=['POST'])
# def post_jobs():
#     new_offer = request.json
#     if not new_offer or 'title' not in new_offer:
#         return jsonify({"error": "Missing title in payload"}), 400
            
    result = jobs_collection.insert_one(new_offer)
    return jsonify({"message": "Job offer created", "id": str(result.inserted_id)}), 201
@jobs_api_bp.route('/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    """Delete a job offer by ID."""
    from bson.objectid import ObjectId
    try:
        result = jobs_collection.delete_one({"_id": ObjectId(job_id)})
        if result.deleted_count == 0:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({"message": "Job deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
#     result = jobs_collection.insert_one(new_offer)
#     return jsonify({"message": "Job offer created", "id": str(result.inserted_id)}), 201

# @jobs_api_bp.route('/jobs/<job_id>/cv-requirement', methods=['GET'])
# def get_job_cv_requirement(job_id):
#     """
#     Get CV requirement info for a specific job.

#     Returns:
#     {
#         "job_id": str,
#         "requires_cv": bool,
#         "cv_required_reason": str | null
#     }
#     """
#     try:
#         object_id = ObjectId(job_id)
#     except Exception:
#         return jsonify({"error": "Invalid job ID"}), 400

#     job = jobs_collection.find_one({"_id": object_id})
#     if not job:
#         return jsonify({"error": "Job not found"}), 404

#     requirements = get_job_cv_requirements(job_id)
#     return jsonify(requirements), 200


# @jobs_api_bp.route('/jobs/<job_id>/validate-cv-requirement/<candidate_id>', methods=['GET'])
# def validate_job_cv_requirement(job_id, candidate_id):
#     """
#     Validate if a candidate meets the CV requirement for a job before applying.

#     Returns:
#     {
#         "valid": bool,
#         "requires_cv": bool,
#         "has_cv": bool,
#         "reason": str | null
#     }
#     """
#     try:
#         object_id = ObjectId(job_id)
#     except Exception:
#         return jsonify({"error": "Invalid job ID"}), 400

#     job = jobs_collection.find_one({"_id": object_id})
#     if not job:
#         return jsonify({"error": "Job not found"}), 404

#     validation_result = validate_cv_requirement_for_application(job_id, candidate_id)
#     return jsonify(validation_result), 200

@jobs_api_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """Get a job offer by ID."""
    from bson.objectid import ObjectId
    try:
        job_doc = jobs_collection.find_one({"_id": ObjectId(job_id)})
        if not job_doc:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(_serialize_job(job_doc)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
