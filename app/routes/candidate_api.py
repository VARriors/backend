from flask import Blueprint, jsonify, request
from bson.objectid import ObjectId
from pymongo.errors import DuplicateKeyError

from app import db
from app.services.candidate_questionnaire_service import (
    SYSTEM_MOBYWATEL_FIELDS,
    SYSTEM_URZAD_PRACY_FIELDS,
    apply_updates,
    build_cv_gate_status,
    get_or_create_questionnaire,
    now_iso,
    parse_object_id,
    questionnaire_completion,
)
from app.services.ledger_service import (
    ALLOWED_DOCUMENT_TYPES,
    append_application_document,
    create_application,
    get_events,
)

candidate_api_bp = Blueprint('candidate_api', __name__)
cv_collection = db['cvs']
candidates_collection = db['candidates']
jobs_collection = db['jobs']
applications_collection = db['applications']


def _normalize_string_list(values):
    if not isinstance(values, list):
        return None

    output = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _unique_lower_strings(values):
    seen = set()
    output = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _derive_skills_from_questionnaire(questionnaire):
    fields = questionnaire.get("fields", {})
    raw = []
    for field_name in ["preferencje", "jezyki", "szkolenia", "kursy", "certyfikaty"]:
        field_payload = fields.get(field_name, {})
        value = field_payload.get("value") if isinstance(field_payload, dict) else None
        if isinstance(value, list):
            raw.extend(value)
    return _unique_lower_strings(raw)


def _extract_candidate_id(payload=None):
    payload = payload or {}
    return (
        request.args.get('candidateId')
        or request.headers.get('X-Candidate-Id')
        or payload.get('candidateId')
        or payload.get('candidate_id')
        or payload.get('user_id')
    )


def _get_candidate_doc(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return None
    return candidates_collection.find_one({"_id": object_id})


def _candidate_employment_payload(candidate_doc):
    status = None
    if isinstance(candidate_doc, dict):
        raw_status = candidate_doc.get("employment_status")
        if isinstance(raw_status, str) and raw_status.strip():
            status = raw_status.strip().lower()

    return {
        "employmentStatus": status,
        "isRegisteredAsUnemployed": status == "unemployed",
        "registeredAsUnemployedAt": candidate_doc.get("registered_as_unemployed_at") if isinstance(candidate_doc, dict) else None,
    }


def _sync_cv_questionnaire_state(candidate_id, questionnaire):
    completion = questionnaire_completion(questionnaire)
    cv_collection.update_one(
        {"user_id": candidate_id},
        {
            "$set": {
                "questionnaire_complete": completion["is_complete"],
                "questionnaire_missing_fields": completion["missing_fields"],
                "updated_at": now_iso(),
            }
        },
    )


def _resolve_job(job_id):
    if not isinstance(job_id, str) or not job_id.strip():
        return None

    clean_job_id = job_id.strip()
    try:
        return jobs_collection.find_one({"_id": ObjectId(clean_job_id)})
    except Exception:
        return jobs_collection.find_one({"id": clean_job_id})


def _normalize_job_id(job_doc, fallback_job_id):
    if job_doc and "_id" in job_doc:
        return str(job_doc["_id"])
    return fallback_job_id


def _normalize_employer_id(value):
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


@candidate_api_bp.route('/context', methods=['GET'])
def get_candidate_context():
    candidate_id = _extract_candidate_id()
    if not candidate_id:
        return jsonify({"error": "Missing Candidate ID"}), 400
        
    candidate = _get_candidate_doc(candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404
        
    questionnaire = get_or_create_questionnaire(candidate)
    completion = questionnaire_completion(questionnaire)
    
    return jsonify({
        "candidateId": str(candidate['_id']),
        "profile": {
            "firstName": candidate.get("first_name"),
            "lastName": candidate.get("last_name")
        },
        "questionnaireComplete": completion["is_complete"],
        "missingFields": completion["missing_fields"],
        **_candidate_employment_payload(candidate),
    }), 200


@candidate_api_bp.route('/register-unemployed', methods=['POST'])
def register_candidate_as_unemployed():
    payload = request.get_json(silent=True) or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    object_id = parse_object_id(candidate_id)
    timestamp = now_iso()
    candidates_collection.update_one(
        {"_id": object_id},
        {
            "$set": {
                "employment_status": "unemployed",
                "registered_as_unemployed_at": timestamp,
                "updated_at": timestamp,
            }
        },
    )

    refreshed_doc = _get_candidate_doc(candidate_id)
    questionnaire = get_or_create_questionnaire(refreshed_doc)
    completion = questionnaire_completion(questionnaire)

    return jsonify({
        "message": "Registered as unemployed",
        "candidateId": candidate_id,
        **_candidate_employment_payload(refreshed_doc),
        "questionnaireComplete": completion.get("is_complete", False),
        "missingFields": completion.get("missing_fields", [])
    }), 200
def _parse_selected_documents(payload):
    raw = payload.get("selected_documents")
    if raw is None:
        raw = payload.get("selectedDocuments")

    if raw is None:
        return [], None

    normalized = _normalize_string_list(raw)
    if normalized is None:
        return None, "selectedDocuments must be an array of strings"

    invalid = [item for item in normalized if item not in ALLOWED_DOCUMENT_TYPES]
    if invalid:
        return None, f"Invalid selected document types: {', '.join(invalid)}"

    return normalized, None


def _merge_unique_strings(*values_lists):
    seen = set()
    merged = []
    for values in values_lists:
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str):
                continue
            normalized = value.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _attach_selected_documents(application_ref, candidate_id, selected_documents):
    attached_count = 0
    for document_type in selected_documents:
        append_application_document(
            application_ref=application_ref,
            document_type=document_type,
            actor_role="candidate",
            actor_id=candidate_id,
            idempotency_key=f"apply-doc-{document_type}",
            verification_status="verified",
            provider="mobywatel",
            note="Attached during one-click apply",
            metadata={"origin": "candidate_apply"},
        )
        attached_count += 1
    return attached_count


def _serialize_candidate_application(app_doc, job_doc=None):
    payload = {
        "applicationId": str(app_doc.get("_id")),
        "candidateId": app_doc.get("candidate_id"),
        "employerId": app_doc.get("employer_id"),
        "jobId": app_doc.get("job_id"),
        "status": app_doc.get("status", "SENT"),
        "createdAt": app_doc.get("created_at"),
        "updatedAt": app_doc.get("updated_at"),
        "selectedDocuments": app_doc.get("selected_documents", []),
    }

    if job_doc:
        payload["job"] = {
            "id": str(job_doc.get("_id")) if job_doc.get("_id") else job_doc.get("id"),
            "title": job_doc.get("title"),
            "company": job_doc.get("company"),
            "location": job_doc.get("location"),
            "category": job_doc.get("category"),
        }

    payload["ledger"] = {
        "applicationRef": app_doc.get("ledger_application_ref"),
        "applicationCommitment": app_doc.get("ledger_application_commitment"),
        "latestStatus": app_doc.get("ledger_latest_status") or app_doc.get("status", "SENT"),
    }

    return payload


# @candidate_api_bp.route('/context', methods=['GET'])
# def get_candidate_context():
#     """
#     Lightweight candidate context endpoint for frontend bootstrap.
#     Requires X-Candidate-Id header.
#     """
#     candidate_id = request.headers.get('X-Candidate-Id')
#     if not candidate_id:
#         return jsonify({
#             "error": "X-Candidate-Id header is required"
#         }), 400

#     candidate_doc = _get_candidate_doc(candidate_id)
#     if not candidate_doc:
#         return jsonify({"error": "Candidate not found"}), 404

#     questionnaire = get_or_create_questionnaire(candidate_doc)
#     completion = questionnaire_completion(questionnaire)

#     fields = questionnaire.get("fields", {}) if isinstance(questionnaire, dict) else {}
#     first_name = (fields.get("imie") or {}).get("value")
#     last_name = (fields.get("nazwisko") or {}).get("value")

#     return jsonify({
#         "candidateId": candidate_id,
#         "profile": {
#             "firstName": first_name,
#             "lastName": last_name,
#         },
#         "questionnaireComplete": completion["is_complete"],
#         "missingFields": completion["missing_fields"],
@candidate_api_bp.route('/cv/status', methods=['GET'])
def get_candidate_cv_status():
    """
    Returns whether the candidate already has a CV in the system.
    Candidate ID can be provided via:
    - query param: candidateId
    - header: X-Candidate-Id
    """
    candidate_id = _extract_candidate_id()

    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param or X-Candidate-Id header)"
        }), 400

    cv_doc = cv_collection.find_one(
        {"user_id": candidate_id},
        {
            "_id": 1,
            "source": 1,
            "file_name": 1,
            "updated_at": 1,
            "created_at": 1,
        },
    )

    candidate_doc = _get_candidate_doc(candidate_id)
    status = build_cv_gate_status(candidate_id, cv_doc, candidate_doc)

    cv_payload = None
    if cv_doc:
        cv_payload = {
            "id": str(cv_doc.get('_id')),
            "source": cv_doc.get('source', 'uploaded'),
            "fileName": cv_doc.get('file_name'),
            "updatedAt": cv_doc.get('updated_at') or cv_doc.get('created_at'),
        }

    return jsonify({
        "candidateId": status["candidate_id"],
        "hasCv": status["has_cv"],
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
        "cv": cv_payload,
    }), 200


@candidate_api_bp.route('/cv/generate', methods=['POST'])
def generate_candidate_cv():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate_doc)
    completion = questionnaire_completion(questionnaire)
    skills = _derive_skills_from_questionnaire(questionnaire)

    cv_doc = {
        "user_id": candidate_id,
        "source": "generated",
        "file_name": f"cv-generated-{candidate_id}.pdf",
        "generated_at": now_iso(),
        "updated_at": now_iso(),
        "skills": skills,
        "questionnaire_complete": completion["is_complete"],
        "questionnaire_missing_fields": completion["missing_fields"],
        "verification_sources": {
            "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
            "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
        },
    }

    existing = cv_collection.find_one({"user_id": candidate_id}, {"_id": 1})
    result = cv_collection.update_one(
        {"user_id": candidate_id},
        {
            "$set": cv_doc,
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )

    cv_id = str(result.upserted_id) if result.upserted_id else str(existing.get("_id"))
    status = build_cv_gate_status(candidate_id, cv_doc, candidate_doc)

    return jsonify({
        "message": "CV generated from verified profile data",
        "candidateId": candidate_id,
        "cvId": cv_id,
        "hasCv": status["has_cv"],
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
    }), 201 if result.upserted_id else 200


@candidate_api_bp.route('/cv/upload', methods=['POST'])
def upload_candidate_cv_pdf():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    file_name = payload.get("fileName") or payload.get("file_name")
    if not isinstance(file_name, str) or not file_name.lower().endswith('.pdf'):
        return jsonify({"error": "fileName is required and must be a PDF filename"}), 400

    mime_type = payload.get("mimeType") or payload.get("mime_type")
    if mime_type and mime_type != "application/pdf":
        return jsonify({"error": "Only application/pdf is supported"}), 400

    questionnaire = get_or_create_questionnaire(candidate_doc)
    completion = questionnaire_completion(questionnaire)

    cv_doc = {
        "user_id": candidate_id,
        "source": "uploaded",
        "file_name": file_name,
        "file_url": payload.get("fileUrl") or payload.get("file_url"),
        "mime_type": "application/pdf",
        "file_size_bytes": payload.get("fileSizeBytes") or payload.get("file_size_bytes"),
        "updated_at": now_iso(),
        "questionnaire_complete": completion["is_complete"],
        "questionnaire_missing_fields": completion["missing_fields"],
        "verification_sources": {
            "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
            "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
        },
    }

    existing = cv_collection.find_one({"user_id": candidate_id}, {"_id": 1})
    result = cv_collection.update_one(
        {"user_id": candidate_id},
        {
            "$set": cv_doc,
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )

    cv_id = str(result.upserted_id) if result.upserted_id else str(existing.get("_id"))
    status = build_cv_gate_status(candidate_id, cv_doc, candidate_doc)

    return jsonify({
        "message": "CV PDF uploaded",
        "candidateId": candidate_id,
        "cvId": cv_id,
        "hasCv": status["has_cv"],
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
    }), 201 if result.upserted_id else 200


@candidate_api_bp.route('/preferences', methods=['PUT'])
def update_candidate_preferences():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    categories = payload.get("categories")
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        return jsonify({"error": "categories must be an array of strings"}), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate_doc)
    user_updates = {
        "preferencje": categories,
    }

    job_area = payload.get("jobArea")
    if isinstance(job_area, str) and job_area.strip():
        user_updates["obszar_poszukiwan"] = job_area.strip()

    errors = apply_updates(questionnaire, user_updates, "user")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    object_id = parse_object_id(candidate_id)
    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    _sync_cv_questionnaire_state(candidate_id, questionnaire)
    cv_doc = cv_collection.find_one({"user_id": candidate_id}, {"_id": 1})
    status = build_cv_gate_status(candidate_id, cv_doc, {"questionnaire": questionnaire})

    return jsonify({
        "message": "Candidate preferences saved",
        "candidateId": candidate_id,
        "categories": categories,
        "questionnaireComplete": status["questionnaire_complete"],
        "missingFields": status["missing_fields"],
        "nextStep": status["next_step"],
    }), 200


@candidate_api_bp.route('/apply', methods=['POST'])
@candidate_api_bp.route('/applications', methods=['POST'])
def apply_to_job_offer():
    payload = request.json or {}
    candidate_id = _extract_candidate_id(payload)
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param, X-Candidate-Id header, or payload)"
        }), 400

    candidate_doc = _get_candidate_doc(candidate_id)
    if not candidate_doc:
        return jsonify({"error": "Candidate not found"}), 404

    job_id = payload.get("job_id") or payload.get("jobId")
    job_doc = _resolve_job(job_id)
    if not job_doc:
        return jsonify({"error": "Job not found"}), 404

    normalized_job_id = _normalize_job_id(job_doc, job_id)
    employer_id = _normalize_employer_id(
        payload.get("employer_id")
        or payload.get("employerId")
        or job_doc.get("employer_id")
        or job_doc.get("employerId")
    )
    if not employer_id:
        return jsonify({"error": "employer_id is required (payload or job.employer_id)"}), 400

    selected_documents, documents_error = _parse_selected_documents(payload)
    if documents_error:
        return jsonify({
            "error": documents_error,
            "allowedDocumentTypes": sorted(ALLOWED_DOCUMENT_TYPES),
        }), 400

    existing = applications_collection.find_one({
        "candidate_id": candidate_id,
        "job_id": normalized_job_id,
        "employer_id": employer_id,
    })

    if existing:
        if not existing.get("ledger_application_ref"):
            ledger_result = create_application(
                candidate_id=candidate_id,
                employer_id=employer_id,
                job_id=normalized_job_id,
                metadata={"origin": "candidate_apply_link"},
            )
            applications_collection.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "status": "SENT",
                        "updated_at": now_iso(),
                        "ledger_application_ref": ledger_result["application_ref"],
                        "ledger_application_commitment": ledger_result["application_commitment"],
                        "ledger_latest_status": "SENT",
                        "ledger_claim_token": ledger_result["claim_token"],
                    }
                },
            )
            existing["ledger_application_ref"] = ledger_result["application_ref"]
            existing["ledger_application_commitment"] = ledger_result["application_commitment"]
            existing["ledger_claim_token"] = ledger_result["claim_token"]
            existing["status"] = "SENT"

        merged_documents = _merge_unique_strings(existing.get("selected_documents", []), selected_documents)
        update_payload = {
            "updated_at": now_iso(),
            "selected_documents": merged_documents,
        }
        if selected_documents:
            update_payload["selected_documents_updated_at"] = now_iso()

        applications_collection.update_one(
            {"_id": existing["_id"]},
            {"$set": update_payload},
        )
        existing["selected_documents"] = merged_documents

        documents_attached_count = 0
        if existing.get("ledger_application_ref") and selected_documents:
            documents_attached_count = _attach_selected_documents(
                application_ref=existing["ledger_application_ref"],
                candidate_id=candidate_id,
                selected_documents=selected_documents,
            )

        return jsonify({
            "message": "Application already exists",
            "applicationId": str(existing["_id"]),
            "candidateId": candidate_id,
            "employerId": employer_id,
            "jobId": normalized_job_id,
            "status": existing.get("status", "SENT"),
            "selectedDocuments": existing.get("selected_documents", []),
            "documentsAttachedCount": documents_attached_count,
            "ledger": {
                "applicationRef": existing.get("ledger_application_ref"),
                "applicationCommitment": existing.get("ledger_application_commitment"),
                "claimToken": existing.get("ledger_claim_token"),
            },
        }), 200

    ledger_result = create_application(
        candidate_id=candidate_id,
        employer_id=employer_id,
        job_id=normalized_job_id,
        metadata={
            "origin": "candidate_apply",
            "job_title": job_doc.get("title"),
        },
    )

    application_doc = {
        "candidate_id": candidate_id,
        "employer_id": employer_id,
        "job_id": normalized_job_id,
        "status": "SENT",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "selected_documents": selected_documents,
        "selected_documents_updated_at": now_iso() if selected_documents else None,
        "ledger_application_ref": ledger_result["application_ref"],
        "ledger_application_commitment": ledger_result["application_commitment"],
        "ledger_latest_status": "SENT",
        "ledger_claim_token": ledger_result["claim_token"],
    }

    documents_attached_count = 0
    if selected_documents:
        documents_attached_count = _attach_selected_documents(
            application_ref=ledger_result["application_ref"],
            candidate_id=candidate_id,
            selected_documents=selected_documents,
        )

    try:
        result = applications_collection.insert_one(application_doc)
    except DuplicateKeyError:
        existing = applications_collection.find_one({
            "candidate_id": candidate_id,
            "job_id": normalized_job_id,
            "employer_id": employer_id,
        })
        if not existing:
            return jsonify({"error": "Failed to save application due to duplicate key"}), 409

        merged_documents = _merge_unique_strings(existing.get("selected_documents", []), selected_documents)
        applications_collection.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "selected_documents": merged_documents,
                    "updated_at": now_iso(),
                    "selected_documents_updated_at": now_iso() if selected_documents else existing.get("selected_documents_updated_at"),
                }
            },
        )

        return jsonify({
            "message": "Application already exists",
            "applicationId": str(existing["_id"]),
            "candidateId": candidate_id,
            "employerId": employer_id,
            "jobId": normalized_job_id,
            "status": existing.get("status", "SENT"),
            "selectedDocuments": merged_documents,
            "documentsAttachedCount": documents_attached_count,
            "ledger": {
                "applicationRef": existing.get("ledger_application_ref"),
                "applicationCommitment": existing.get("ledger_application_commitment"),
                "claimToken": existing.get("ledger_claim_token"),
            },
        }), 200

    return jsonify({
        "message": "Application created",
        "applicationId": str(result.inserted_id),
        "candidateId": candidate_id,
        "employerId": employer_id,
        "jobId": normalized_job_id,
        "status": "SENT",
        "selectedDocuments": selected_documents,
        "documentsAttachedCount": documents_attached_count,
        "ledger": {
            "applicationRef": ledger_result["application_ref"],
            "applicationCommitment": ledger_result["application_commitment"],
            "claimToken": ledger_result["claim_token"],
        },
    }), 201


@candidate_api_bp.route('/applications', methods=['GET'])
def list_candidate_applications():
    candidate_id = _extract_candidate_id()
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param or X-Candidate-Id header)"
        }), 400

    requested_job_id = request.args.get("jobId") or request.args.get("job_id")
    normalized_job_id = None
    if isinstance(requested_job_id, str) and requested_job_id.strip():
        resolved_job = _resolve_job(requested_job_id)
        if not resolved_job:
            return jsonify({"error": "Job not found"}), 404
        normalized_job_id = _normalize_job_id(resolved_job, requested_job_id.strip())

    mongo_filter = {"candidate_id": candidate_id}
    if normalized_job_id:
        mongo_filter["job_id"] = normalized_job_id

    app_docs = list(
        applications_collection
        .find(mongo_filter)
        .sort("created_at", -1)
    )

    job_ids = [app_doc.get("job_id") for app_doc in app_docs if isinstance(app_doc.get("job_id"), str)]
    object_ids = []
    for job_id in job_ids:
        try:
            object_ids.append(ObjectId(job_id))
        except Exception:
            continue

    jobs_map = {}
    if object_ids:
        for job_doc in jobs_collection.find({"_id": {"$in": object_ids}}):
            jobs_map[str(job_doc.get("_id"))] = job_doc

    response_items = []
    for app_doc in app_docs:
        job_doc = jobs_map.get(app_doc.get("job_id"))
        response_items.append(_serialize_candidate_application(app_doc, job_doc))

    return jsonify({
        "candidateId": candidate_id,
        "jobId": normalized_job_id,
        "items": response_items,
        "total": len(response_items),
    }), 200


@candidate_api_bp.route('/applications/<application_id>', methods=['GET'])
def get_candidate_application_details(application_id):
    candidate_id = _extract_candidate_id()
    if not candidate_id:
        return jsonify({
            "error": "candidateId is required (query param or X-Candidate-Id header)"
        }), 400

    object_id = parse_object_id(application_id)
    if not object_id:
        return jsonify({"error": "Invalid application ID"}), 400

    app_doc = applications_collection.find_one({"_id": object_id})
    if not app_doc:
        return jsonify({"error": "Application not found"}), 404

    if app_doc.get("candidate_id") != candidate_id:
        return jsonify({"error": "Application does not belong to candidate"}), 403

    job_doc = _resolve_job(app_doc.get("job_id"))
    response_payload = _serialize_candidate_application(app_doc, job_doc)

    ledger_ref = app_doc.get("ledger_application_ref")
    timeline_summary = None
    if ledger_ref:
        events = get_events(ledger_ref)
        serialized_events = []
        for event in events:
            serialized_events.append({
                "id": str(event.get("_id")),
                "statusCode": event.get("status_code"),
                "eventTime": event.get("event_time"),
                "actorRole": event.get("actor_role"),
                "actorId": event.get("actor_id"),
                "note": event.get("note"),
            })

        last_event = events[-1] if events else None
        timeline_summary = {
            "eventsCount": len(events),
            "events": serialized_events,
            "lastEvent": {
                "statusCode": last_event.get("status_code"),
                "eventTime": last_event.get("event_time"),
                "actorRole": last_event.get("actor_role"),
            } if last_event else None,
        }

    response_payload["timeline"] = timeline_summary
    return jsonify(response_payload), 200
