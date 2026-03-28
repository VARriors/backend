from flask import Blueprint, jsonify, request
from bson.errors import InvalidId
from bson.objectid import ObjectId

from app import db


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
        "employmentType": job_doc.get("employment_type"),
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

@jobs_api_bp.route('/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    try:
        obj_id = ObjectId(job_id)
    except InvalidId:
        return jsonify({"error": "Invalid job ID format"}), 400

    job_doc = jobs_collection.find_one({"_id": obj_id})
    if not job_doc:
        return jsonify({"error": "Job offer not found"}), 404

    return jsonify(_serialize_job(job_doc)), 200

