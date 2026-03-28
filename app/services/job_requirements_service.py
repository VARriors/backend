"""
Job requirements service.

Handles CV requirements and validation for job postings.
"""

from typing import Optional, Dict, Any
from app import db

jobs_collection = db['jobs']


def get_job_cv_requirements(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get CV requirement info for a specific job.

    Args:
        job_id: Job ID as string

    Returns:
        Dict with {
            "job_id": str,
            "requires_cv": bool,
            "cv_required_reason": str | null
        } or None if job not found
    """
    try:
        from bson import ObjectId

        object_id = ObjectId(job_id)
        job = jobs_collection.find_one({"_id": object_id})

        if not job:
            return None

        return {
            "job_id": job_id,
            "requires_cv": job.get("requires_cv", False),
            "cv_required_reason": job.get("cv_required_reason"),
        }

    except Exception:
        return None


def has_candidate_cv(candidate_id: str) -> bool:
    """
    Check if a candidate has a CV uploaded.

    Args:
        candidate_id: Candidate ID

    Returns:
        True if candidate has CV in questionnaire, False otherwise
    """
    try:
        from bson import ObjectId

        candidates_collection = db['candidates']
        object_id = ObjectId(candidate_id)

        candidate = candidates_collection.find_one({"_id": object_id})
        if not candidate:
            return False

        questionnaire = candidate.get("questionnaire", {})
        cv_field = questionnaire.get("fields", {}).get("cv", {})

        return cv_field.get("value") is not None

    except Exception:
        return False


def validate_cv_requirement_for_application(
    job_id: str,
    candidate_id: str,
) -> Dict[str, Any]:
    """
    Validate if a candidate meets the CV requirement for a job.

    Args:
        job_id: Job ID
        candidate_id: Candidate ID

    Returns:
        Dict with {
            "valid": bool,
            "requires_cv": bool,
            "has_cv": bool,
            "reason": str | null
        }
    """
    requirements = get_job_cv_requirements(job_id)
    if not requirements:
        return {
            "valid": False,
            "requires_cv": False,
            "has_cv": False,
            "reason": "Job not found",
        }

    requires_cv = requirements["requires_cv"]
    has_cv = has_candidate_cv(candidate_id)

    valid = not requires_cv or (requires_cv and has_cv)
    reason = None

    if not valid:
        reason = requirements.get("cv_required_reason") or (
            "This job requires a CV. Please upload your CV to apply."
        )

    return {
        "valid": valid,
        "requires_cv": requires_cv,
        "has_cv": has_cv,
        "reason": reason,
    }
