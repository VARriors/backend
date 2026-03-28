from io import BytesIO
from flask import Blueprint, jsonify, request, send_file
from bson.objectid import ObjectId

from app import db
from app.services.candidate_questionnaire_service import (
    SYSTEM_MOBYWATEL_FIELDS,
    SYSTEM_URZAD_PRACY_FIELDS,
    FIELD_SOURCE_MAP,
    apply_updates,
    build_cv_gate_status,
    get_or_create_questionnaire,
    now_iso,
    parse_object_id,
    questionnaire_completion,
)
from app.services.cv_service import process_cv_file, get_cv_metadata, delete_cv_file


candidate_questionnaire_bp = Blueprint('candidate_questionnaire', __name__)
candidates_collection = db['candidates']
cv_collection = db['cvs']


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>', methods=['GET'])
def get_questionnaire(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    completion = questionnaire_completion(questionnaire)

    return jsonify({
        "candidate_id": candidate_id,
        "questionnaire": questionnaire,
        "completion": completion,
        "field_sources": FIELD_SOURCE_MAP,
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/user-input', methods=['PUT'])
def upsert_user_questionnaire(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    payload = request.json or {}
    updates = payload.get("fields")
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "Missing 'fields' payload"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    errors = apply_updates(questionnaire, updates, "user")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    return jsonify({
        "message": "Questionnaire updated",
        "candidate_id": candidate_id,
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/mobywatel', methods=['PUT'])
def merge_mobywatel_data(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    payload = request.json or {}
    updates = payload.get("fields")
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "Missing 'fields' payload"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    errors = apply_updates(questionnaire, updates, "mobywatel")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    return jsonify({
        "message": "mObywatel data merged and verified",
        "candidate_id": candidate_id,
        "verified_fields": sorted(list(updates.keys())),
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/urzad-pracy', methods=['PUT'])
def merge_urzad_pracy_data(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    payload = request.json or {}
    updates = payload.get("fields")
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "Missing 'fields' payload"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    errors = apply_updates(questionnaire, updates, "urzad_pracy")
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire}},
    )

    return jsonify({
        "message": "Urzad Pracy data merged and verified",
        "candidate_id": candidate_id,
        "verified_fields": sorted(list(updates.keys())),
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/verification-summary', methods=['GET'])
def questionnaire_verification_summary(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    fields = questionnaire.get("fields", {})
    summary = {
        "verified": 0,
        "pending": 0,
        "unverified": 0,
        "rejected": 0,
        "total": len(fields),
    }

    per_field = {}
    for field_name, payload in fields.items():
        verification = payload.get("verification", {})
        status = verification.get("status", "unverified")
        if status in summary:
            summary[status] += 1
        per_field[field_name] = {
            "source": verification.get("source"),
            "status": status,
            "verified_by": verification.get("verified_by"),
            "verified_at": verification.get("verified_at"),
        }

    return jsonify({
        "candidate_id": candidate_id,
        "summary": summary,
        "per_field": per_field,
        "completion": questionnaire_completion(questionnaire),
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/seed-demo', methods=['POST'])
def seed_demo_questionnaire():
    payload = request.json or {}

    first_name = payload.get("first_name") or "Jan"
    last_name = payload.get("last_name") or "Kowalski"
    create_cv = bool(payload.get("create_cv", True))

    candidate_doc = {
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    result = candidates_collection.insert_one(candidate_doc)
    candidate_id = str(result.inserted_id)
    candidate = candidates_collection.find_one({"_id": result.inserted_id})
    questionnaire = get_or_create_questionnaire(candidate)

    mobywatel_updates = {
        "imie": first_name,
        "nazwisko": last_name,
        "pesel": "90010112345",
        "dowod": "ABC123456",
        "niepelnosprawnosc": False,
    }
    user_updates = {
        "nr_telefonu": "+48500111222",
        "email": f"{str(first_name).lower()}.{str(last_name).lower()}@example.com",
        "preferencje": ["IT / Technologia", "Administracja"],
        "obszar_poszukiwan": "mazowieckie, Warszawa",
        "jezyki": ["Angielski (B2)", "Polski (natywny)"],
        "szkolenia": ["Kurs React"],
        "kursy": ["Kurs Python"],
        "certyfikaty": ["AWS Cloud Practitioner"],
        "aktywnosc_dodatkowa": ["Wolontariat"],
    }
    urzad_pracy_updates = {
        "doswiadczenia_zawodowe": [
            {
                "stanowisko": "Specjalista IT",
                "firma": "GovTech Solutions",
                "od": "2022-01",
                "do": "2024-12",
            }
        ]
    }

    errors = []
    errors.extend(apply_updates(questionnaire, mobywatel_updates, "mobywatel"))
    errors.extend(apply_updates(questionnaire, user_updates, "user"))
    errors.extend(apply_updates(questionnaire, urzad_pracy_updates, "urzad_pracy"))

    if errors:
        candidates_collection.delete_one({"_id": result.inserted_id})
        return jsonify({"error": "Seed validation failed", "details": errors}), 400

    candidates_collection.update_one(
        {"_id": result.inserted_id},
        {"$set": {"questionnaire": questionnaire, "updated_at": now_iso()}},
    )

    completion = questionnaire_completion(questionnaire)

    if create_cv:
        cv_collection.update_one(
            {"user_id": candidate_id},
            {
                "$set": {
                    "user_id": candidate_id,
                    "source": "generated",
                    "file_name": f"cv-generated-{candidate_id}.pdf",
                    "generated_at": now_iso(),
                    "updated_at": now_iso(),
                    "questionnaire_complete": completion["is_complete"],
                    "questionnaire_missing_fields": completion["missing_fields"],
                    "verification_sources": {
                        "mobywatel": SYSTEM_MOBYWATEL_FIELDS,
                        "urzad_pracy": SYSTEM_URZAD_PRACY_FIELDS,
                    },
                },
                "$setOnInsert": {"created_at": now_iso()},
            },
            upsert=True,
        )

    return jsonify({
        "message": "Demo candidate seeded",
        "candidate_id": candidate_id,
        "create_cv": create_cv,
        "completion": completion,
    }), 201


@candidate_questionnaire_bp.route('/cv/status/<candidate_id>', methods=['GET'])
def get_cv_status(candidate_id):
    cv_doc = cv_collection.find_one({"user_id": candidate_id})

    object_id = parse_object_id(candidate_id)
    candidate = candidates_collection.find_one({"_id": object_id}) if object_id else None
    status = build_cv_gate_status(candidate_id, cv_doc, candidate)
    return jsonify(status), 200


@candidate_questionnaire_bp.route('/questionnaire/seed-demo', methods=['POST'])
def seed_demo_candidate():
    data = request.json or {}
    first_name = data.get("first_name", "Jan")
    last_name = data.get("last_name", "Kowalski")
    candidate_id = "65f1a2b3c4d5e6f7a8b9c0d1"
    object_id = ObjectId(candidate_id)

    # Clean existing
    candidates_collection.delete_one({"_id": object_id})
    cv_collection.delete_one({"user_id": candidate_id})

    questionnaire = get_or_create_questionnaire(None)
    questionnaire["fields"]["imie"]["value"] = first_name
    questionnaire["fields"]["pesel"]["value"] = "12345678901"
    questionnaire["fields"]["dowod"]["value"] = "ABC123456"
    questionnaire["fields"]["nazwisko"]["value"] = last_name

    candidate = {
        "_id": object_id,
        "first_name": first_name,
        "last_name": last_name,
        "email": f"{first_name.lower()}.{last_name.lower()}@example.com",
        "questionnaire": questionnaire,
        "created_at": now_iso()
    }
# @candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/cv-upload', methods=['POST'])
# def upload_cv(candidate_id):
#     """
#     Upload a CV file (PDF) and extract text/data.

#     Expected request:
#     - multipart/form-data with 'file' field containing PDF
#     - Optional 'job_id' field for job-specific tracking

#     Returns:
#     - file_id: GridFS file ID
#     - extraction_status: "success" | "failed"
#     - extracted_data: { email, phone, languages, skills } or null
#     """
#     object_id = parse_object_id(candidate_id)
#     if not object_id:
#         return jsonify({"error": "Invalid candidate ID"}), 400

#     candidate = candidates_collection.find_one({"_id": object_id})
#     if not candidate:
#         return jsonify({"error": "Candidate not found"}), 404

#     # Check for file in request
#     if "file" not in request.files:
#         return jsonify({"error": "No file uploaded"}), 400

#     file = request.files["file"]
#     if file.filename == "":
#         return jsonify({"error": "No file selected"}), 400

#     # Validate file type
#     if not file.filename.lower().endswith(".pdf"):
#         return jsonify({"error": "Only PDF files are supported"}), 400

#     # Check file size (5MB limit)
#     file.seek(0, 2)  # Seek to end
#     file_size = file.tell()
#     file.seek(0)  # Reset to beginning

#     if file_size > 5 * 1024 * 1024:  # 5MB
#         return jsonify({"error": "File size exceeds 5MB limit"}), 400

#     # Read file bytes
#     file_bytes = file.read()

#     try:
#         # Process CV: extract text and parse fields
#         cv_result = process_cv_file(file_bytes, file.filename, candidate_id)

#         # Update questionnaire with CV field
#         questionnaire = get_or_create_questionnaire(candidate)

#         # CV field contains file metadata (without the full extracted_data in verification)
#         cv_field_value = {
#             "file_id": cv_result["file_id"],
#             "filename": file.filename,
#             "uploaded_at": now_iso(),
#             "extraction_status": cv_result["extraction_status"],
#             "extracted_data": cv_result.get("extracted_data"),
#         }

#         # Apply CV update to questionnaire
#         errors = apply_updates(questionnaire, {"cv": cv_field_value}, "user")
#         if errors:
#             return jsonify({"error": "Failed to update questionnaire", "details": errors}), 400

#         candidates_collection.update_one(
#             {"_id": object_id},
#             {"$set": {"questionnaire": questionnaire, "updated_at": now_iso()}},
#         )

@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/cv', methods=['GET'])
def get_cv_info(candidate_id):
    """
    Get CV metadata and extracted data for a candidate.

    Does NOT return the file bytes (use separate download endpoint for that).

    Returns:
    - file_id, filename, uploaded_at, extraction_status, extracted_data
    """
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid candidate ID"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    cv_field = questionnaire.get("fields", {}).get("cv", {})

    if not cv_field or not cv_field.get("value"):
        return jsonify({"cv": None}), 200

    cv_value = cv_field.get("value", {})

    return jsonify({
        "cv": {
            "file_id": cv_value.get("file_id"),
            "filename": cv_value.get("filename"),
            "uploaded_at": cv_value.get("uploaded_at"),
            "extraction_status": cv_value.get("extraction_status"),
            "extracted_data": cv_value.get("extracted_data"),
        }
    }), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/cv', methods=['DELETE'])
def delete_cv(candidate_id):
    """
    Delete a CV file from GridFS and clear it from the questionnaire.

    Extracted keywords in questionnaire are preserved for reference.

    Returns:
    - success message
    """
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid candidate ID"}), 400

    candidate = candidates_collection.find_one({"_id": object_id})
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    questionnaire = get_or_create_questionnaire(candidate)
    cv_field = questionnaire.get("fields", {}).get("cv", {})

    if not cv_field or not cv_field.get("value"):
        return jsonify({
            "message": "No CV found for this candidate",
            "candidate_id": candidate_id,
        }), 200

    cv_value = cv_field.get("value", {})
    file_id = cv_value.get("file_id")

    if file_id:
        # Best-effort delete from GridFS; questionnaire cleanup below is always applied.
        delete_cv_file(file_id)

    # Keep schema stable: clear value instead of removing field entirely.
    fields = questionnaire.setdefault("fields", {})
    fields["cv"] = {
        "value": None,
        "verification": {
            "source": "user",
            "status": "unverified",
            "verified_by": None,
            "verified_at": None,
            "note": None,
        },
    }
    questionnaire["updated_at"] = now_iso()

    candidates_collection.update_one(
        {"_id": object_id},
        {"$set": {"questionnaire": questionnaire, "updated_at": now_iso()}},
    )

    return jsonify({
        "message": "CV deleted successfully",
        "candidate_id": candidate_id,
        "questionnaire": questionnaire
    }), 201

@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/cv', methods=['GET', 'DELETE'])
def candidate_cv_operations(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    if request.method == 'GET':
        cv_doc = cv_collection.find_one({"user_id": candidate_id})
        
        if not cv_doc:
            return jsonify({"cv": None}), 200
            
        return jsonify({
            "cv": {
                "file_id": str(cv_doc.get("_id", "")),
                "filename": cv_doc.get("filename", "cv.pdf"),
                "uploaded_at": cv_doc.get("created_at"),
                "extraction_status": cv_doc.get("extraction_status", "success" if cv_doc.get("has_cv") else "pending"),
                "extracted_data": cv_doc.get("extracted_data", {})
            }
        }), 200
        
    elif request.method == 'DELETE':
        cv_collection.delete_one({"user_id": candidate_id})
        return jsonify({"message": "CV deleted successfuly"}), 200


@candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/cv-upload', methods=['POST'])
def candidate_cv_upload_form(candidate_id):
    object_id = parse_object_id(candidate_id)
    if not object_id:
        return jsonify({"error": "Invalid ID"}), 400

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400

    # Hackathon stub for extraction
    extracted = {
        "email": "jan.kowalski@example.com",
        "phone": "123456789",
        "languages": [{"jezyk": "Angielski", "poziom": "B2"}],
        "skills": ["Python", "JavaScript"]
    }
    
    cv_doc = {
        "user_id": candidate_id,
        "filename": file.filename,
        "has_cv": True,
        "extraction_status": "success",
        "extracted_data": extracted,
        "created_at": now_iso()
    }
    
    # upsert
    cv_collection.update_one(
        {"user_id": candidate_id},
        {"$set": cv_doc},
        upsert=True
    )
    
    inserted_doc = cv_collection.find_one({"user_id": candidate_id})

    return jsonify({
        "file_id": str(inserted_doc.get("_id", "")),
        "extraction_status": "success",
        "extracted_data": extracted
    }), 200

#     }), 200


# @candidate_questionnaire_bp.route('/questionnaire/<candidate_id>/cv-file/<file_id>', methods=['GET'])
# def download_cv(candidate_id, file_id):
#     """
#     Download a CV file from GridFS.

#     Args:
#         candidate_id: Candidate ID (for authorization check)
#         file_id: GridFS file ID

#     Returns:
#         PDF file bytes with appropriate headers
#     """
#     from app.services.cv_service import get_cv_file

#     object_id = parse_object_id(candidate_id)
#     if not object_id:
#         return jsonify({"error": "Invalid candidate ID"}), 400

#     candidate = candidates_collection.find_one({"_id": object_id})
#     if not candidate:
#         return jsonify({"error": "Candidate not found"}), 404

#     # Validate that the file belongs to this candidate
#     questionnaire = get_or_create_questionnaire(candidate)
#     cv_field = questionnaire.get("fields", {}).get("cv", {})
#     cv_value = cv_field.get("value", {})
#     stored_file_id = cv_value.get("file_id")

#     if not stored_file_id or stored_file_id != file_id:
#         return jsonify({"error": "CV file not found or does not belong to this candidate"}), 404

#     # Retrieve file from GridFS
#     file_bytes = get_cv_file(file_id)
#     if not file_bytes:
#         return jsonify({"error": "File not found in storage"}), 404

#     return send_file(
#         BytesIO(file_bytes),
#         mimetype="application/pdf",
#         as_attachment=False,
#         download_name=cv_value.get("filename", "cv.pdf"),
#     )
