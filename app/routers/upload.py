"""
AceCPAs Backend - Upload Router
File upload endpoint for GL Excel files.
"""
import uuid
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Query
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import get_supabase_admin_client
from app.models.schemas import (
    FileUploadResponse,
    UploadJobResponse,
    ErrorResponse
)
from app.workers.tasks import process_gl_file

router = APIRouter()
settings = get_settings()

# Allowed file extensions
ALLOWED_EXTENSIONS = {'.xlsx', '.xls'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.post(
    "/upload",
    response_model=FileUploadResponse,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
    },
    summary="Upload GL Excel file",
    description="Upload an Excel file containing GL transactions. The file will be processed asynchronously."
)
async def upload_gl_file(
    deal_id: str = Query(..., description="UUID of the deal to upload transactions to"),
    file: UploadFile = File(..., description="Excel file (.xlsx or .xls)")
):
    """
    Upload a GL Excel file for processing.
    
    The file will be:
    1. Validated for format and size
    2. Saved to Supabase Storage
    3. Queued for async processing via Celery
    
    Returns a job_id to track processing status.
    """
    # Validate file extension
    filename = file.filename or "upload.xlsx"
    extension = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
        )
    
    if file_size == 0:
        raise HTTPException(
            status_code=400,
            detail="Empty file uploaded"
        )
    
    # Generate unique file path
    file_id = str(uuid.uuid4())
    storage_path = f"gl-files/{deal_id}/{file_id}{extension}"
    
    try:
        # Upload to Supabase Storage
        client = get_supabase_admin_client()
        storage = client.storage.from_("deal_files") # Ensure this matches your bucket
        
        # Upload file
        storage.upload(
            path=storage_path,
            file=content,
            file_options={"content-type": file.content_type or "application/octet-stream"}
        )

        # 1. Fetch Organization ID (Required for 'files' table)
        deal_res = client.table("deals").select("organization_id").eq("id", deal_id).single().execute()
        if not deal_res.data:
             raise HTTPException(status_code=404, detail="Deal not found")
        org_id = deal_res.data["organization_id"]
        
        # 2. Insert into 'files' table (Existing schema)
        job_id = str(uuid.uuid4()) # We can use file ID as job ID or create a new one. 
        # Using file_id as the PK for 'files' makes sense usually.
        # Let's use file_id generated earlier.
        
        file_record = {
            "id": file_id,
            "deal_id": deal_id,
            "organization_id": org_id,
            "filename": filename,
            "original_filename": filename,
            "storage_path": storage_path,
            "file_size": file_size,
            "file_type": file.content_type or extension,
            "status": "pending", # Enum: file_status
            "uploaded_by": None # We don't have user ID in backend proxy yet, unless passed.
            # "error_message": None
        }
        
        client.table("files").insert(file_record).execute()
        
        # Queue Celery task (or run sync if no Redis)
        # process_gl_file.delay(...) -> Requires Redis
        
        # FOR LOCAL DEV WITHOUT REDIS: Run synchronously
        print("WARNING: Running task synchronously (No Redis)")
        process_gl_file(
            job_id=file_id,
            deal_id=deal_id,
            file_path=storage_path,
            filename=filename
        )
        
        return FileUploadResponse(
            job_id=uuid.UUID(file_id),
            message=f"File '{filename}' uploaded successfully. Processing started."
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()  # Force print to console
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {str(e)}"
        )


@router.get(
    "/upload/{job_id}/status",
    response_model=UploadJobResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get upload job status",
    description="Check the status of an upload job by its ID."
)
async def get_upload_status(job_id: str):
    """Get the status of an upload job."""
    try:
        client = get_supabase_admin_client()
        result = client.table("upload_jobs").select("*").eq("id", job_id).single().execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return result.data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
