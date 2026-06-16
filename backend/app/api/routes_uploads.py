"""
File Upload API.

Responsibilities
---------------
- Accept PDF/image uploads
- Validate file types
- Persist files locally
- Return metadata required by ExtractionAgent

Future:
- Replace local storage with S3/GCS
- Virus scanning
- Async background processing
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    UploadFile,
    status,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])

# ============================================================================
# Configuration
# ============================================================================

UPLOAD_DIR = Path("storage/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/jpg",
}

MAX_FILE_SIZE_MB = 20


# ============================================================================
# Helpers
# ============================================================================


def validate_file_type(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type: "
                f"{file.content_type}. "
                "Only PDF, JPG and PNG are allowed."
            ),
        )


def validate_file_size(file_path: Path) -> None:
    size_mb = file_path.stat().st_size / (1024 * 1024)

    if size_mb > MAX_FILE_SIZE_MB:
        file_path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File exceeds maximum size of "
                f"{MAX_FILE_SIZE_MB}MB."
            ),
        )


# ============================================================================
# POST /uploads
# ============================================================================


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
):
    """
    Upload PDF/image.

    Returns metadata used by:
        DocumentClassifier
        ExtractionAgent
    """

    validate_file_type(file)

    file_id = str(uuid.uuid4())

    extension = Path(file.filename).suffix

    stored_name = f"{file_id}{extension}"

    destination = UPLOAD_DIR / stored_name

    try:
        with destination.open("wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer,
            )

        validate_file_size(destination)

        return {
            "file_id": file_id,
            "file_name": file.filename,
            "mime_type": file.content_type,
            "file_path": str(destination),
            "size_bytes": destination.stat().st_size,
            "status": "UPLOADED",
        }

    except Exception as exc:
        destination.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(exc)}",
        )


# ============================================================================
# GET /uploads/{file_id}
# ============================================================================


@router.get("/{file_id}")
async def get_upload_metadata(
    file_id: str,
):
    """
    Lookup uploaded file metadata.

    Useful for debugging/demo.
    """

    matches = list(
        UPLOAD_DIR.glob(f"{file_id}.*")
    )

    if not matches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    file_path = matches[0]

    return {
        "file_id": file_id,
        "file_name": file_path.name,
        "file_path": str(file_path),
        "size_bytes": file_path.stat().st_size,
    }


# ============================================================================
# DELETE /uploads/{file_id}
# ============================================================================


@router.delete("/{file_id}")
async def delete_upload(
    file_id: str,
):
    """
    Delete uploaded file.
    """

    matches = list(
        UPLOAD_DIR.glob(f"{file_id}.*")
    )

    if not matches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    matches[0].unlink()

    return {
        "message": "Upload deleted",
        "file_id": file_id,
    }