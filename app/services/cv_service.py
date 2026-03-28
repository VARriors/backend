"""
CV file management service using MongoDB GridFS.

Handles uploading, retrieving, and deleting CV PDF files,
as well as full CV processing (extraction + parsing).
"""

from io import BytesIO
from datetime import datetime, timezone
from typing import Optional, Dict, Any


from app.db import get_db
from app.utils.cv_extraction import extract_and_parse_cv, ExtractedCVData


def get_gridfs():
    """Get GridFS instance from current database."""
    from gridfs import GridFS

    db = get_db()
    return GridFS(db, collection="cv_files")


def upload_cv_file(
    file_bytes: bytes,
    filename: str,
    candidate_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Upload a CV PDF file to MongoDB GridFS.

    Args:
        file_bytes: Raw PDF file content
        filename: Original filename (e.g., "resume.pdf")
        candidate_id: Associated candidate ID
        metadata: Optional metadata dict

    Returns:
        GridFS file_id (ObjectId as string)

    Raises:
        Exception: If upload fails
    """
    try:
        gridfs = get_gridfs()

        file_metadata = {
            "candidate_id": str(candidate_id),
            "original_filename": filename,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }

        file_id = gridfs.put(
            file_bytes,
            filename=filename,
            metadata=file_metadata,
        )

        return str(file_id)

    except Exception as e:
        raise Exception(f"Failed to upload CV file: {e}")


def get_cv_file(file_id: str) -> Optional[bytes]:
    """
    Retrieve a CV PDF file from GridFS.

    Args:
        file_id: GridFS file_id (as string or ObjectId)

    Returns:
        File bytes or None if not found

    Raises:
        GridFSError: If retrieval fails
    """
    try:
        from bson import ObjectId

        gridfs = get_gridfs()
        object_id = ObjectId(file_id)
        grid_file = gridfs.get(object_id)
        return grid_file.read()

    except Exception as e:
        return None


def delete_cv_file(file_id: str) -> bool:
    """
    Delete a CV PDF file from GridFS.

    Args:
        file_id: GridFS file_id (as string or ObjectId)

    Returns:
        True if deleted, False if not found

    Raises:
        Exception: If deletion fails
    """
    try:
        from bson import ObjectId

        gridfs = get_gridfs()
        object_id = ObjectId(file_id)
        gridfs.delete(object_id)
        return True

    except Exception:
        return False


def process_cv_file(
    file_bytes: bytes,
    filename: str,
    candidate_id: str,
) -> Dict[str, Any]:
    """
    Complete CV processing pipeline:
    1. Extract text from PDF
    2. Parse extracted data (email, phone, languages, skills)
    3. Upload file to GridFS
    4. Return structured result

    Args:
        file_bytes: Raw PDF file content
        filename: Original filename
        candidate_id: Associated candidate ID

    Returns:
        Dict with keys:
        - file_id: GridFS file_id
        - extraction_status: "success" | "failed"
        - extracted_data: { email, phone, languages, skills } or null
        - error: Error message if extraction failed

    Raises:
        Exception: If file upload fails
    """
    # Extract and parse CV
    extracted_data = extract_and_parse_cv(file_bytes)

    extraction_status = "success" if extracted_data else "failed"
    error = None if extracted_data else "Failed to extract text from PDF"

    # Upload file to GridFS
    metadata = {
        "extraction_status": extraction_status,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    file_id = upload_cv_file(file_bytes, filename, candidate_id, metadata)

    return {
        "file_id": file_id,
        "extraction_status": extraction_status,
        "extracted_data": extracted_data.to_dict() if extracted_data else None,
        "error": error,
    }


def get_cv_metadata(file_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve metadata for a CV file without downloading the full file.

    Args:
        file_id: GridFS file_id (as string or ObjectId)

    Returns:
        Metadata dict or None if not found
    """
    try:
        from bson import ObjectId

        gridfs = get_gridfs()
        object_id = ObjectId(file_id)
        grid_file = gridfs.get(object_id)

        return {
            "file_id": str(grid_file._id),
            "filename": grid_file.filename,
            "uploaded_at": grid_file.metadata.get("uploaded_at"),
            "candidate_id": grid_file.metadata.get("candidate_id"),
            "extraction_status": grid_file.metadata.get("extraction_status"),
        }

    except Exception:
        return None
