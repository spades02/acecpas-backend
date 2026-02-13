import uuid
from datetime import datetime
from fastapi import APIRouter, File, UploadFile, HTTPException, Query, Path, BackgroundTasks
from pydantic import ValidationError
from typing import Optional

from app.database import get_supabase_admin_client
from app.models.qoe_schemas import UploadedFileResponse, FileType
from app.services.pl_ingestion import PLIngestionService
from app.services.ingestion import IngestionService

# Initialize services
pl_service = PLIngestionService()
gl_service = IngestionService()

router = APIRouter()

ALLOWED_EXTENSIONS = {'.xlsx', '.xls', '.csv'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

@router.post(
    "/deals/{deal_id}/files",
    response_model=UploadedFileResponse,
    summary="Upload Financial File",
    description="Upload a financial file (P&L, GL, etc.) for a specific deal."
)
async def upload_deal_file(
    background_tasks: BackgroundTasks,
    deal_id: str = Path(..., description="UUID of the deal"),
    file: UploadFile = File(...),
    file_type: FileType = Query(..., description="Type of file being uploaded")
):
    # Validate file extension
    filename = file.filename or "upload"
    extension = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
        
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")
        
    # Generate storage path
    file_id = str(uuid.uuid4())
    storage_path = f"{deal_id}/{file_type}/{file_id}{extension}"
    
    try:
        client = get_supabase_admin_client()
        
        # Get Organization ID
        deal_res = client.table("deals").select("organization_id").eq("id", deal_id).single().execute()
        if not deal_res.data:
            raise HTTPException(status_code=404, detail="Deal not found")
        
        org_id = deal_res.data["organization_id"]
        
        # Upload to Storage
        # Ensure 'financial_files' bucket exists or use 'deal_files'
        bucket_name = "deal_files" 
        try:
             client.storage.from_(bucket_name).upload(
                path=storage_path,
                file=content,
                file_options={"content-type": file.content_type}
            )
        except Exception as e:
             # Handle bucket missing or upload error
             print(f"Storage upload failed: {e}")
             raise HTTPException(status_code=500, detail="Failed to upload file to storage")

        # Create DB record
        new_file = {
            "id": file_id,
            "deal_id": deal_id,
            "organization_id": org_id,
            "file_type": file_type,
            "original_filename": filename,
            "storage_path": storage_path,
            "file_size_bytes": file_size,
            "status": "pending",
            "uploaded_by": None # TODO: Get user from auth context
        }
        
        res = client.table("uploaded_files").insert(new_file).execute()
        
        if not res.data:
             raise HTTPException(status_code=500, detail="Failed to create database record")
             
        # Trigger Processing in Background
        background_tasks.add_task(process_upload_task, deal_id, file_id, content, filename, file_type)
        
        return res.data[0]

    except Exception as e:
        print(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_upload_task(deal_id: str, file_id: str, content: bytes, filename: str, file_type: str):
    """Background task to process the uploaded file."""
    try:
        print(f"Starting background processing for {file_type} file {file_id}")
        if file_type == 'monthly_pl':
             # Re-instantiate service inside task to be safe? Or use global.
             # Global `pl_service` is stateless enough.
             pl_service.process_file(deal_id, file_id, content, filename)
        elif file_type == 'gl_detail':
             _process_gl_file(deal_id, file_id, content, filename)
        else:
             print(f"No parser for {file_type}")
             
    except Exception as e:
        print(f"Background processing failed: {e}")
        # Status update to 'failed' is handled inside services usually, but catch-all here
        supabase = get_supabase_admin_client()
        supabase.table("uploaded_files").update({
            "status": "failed",
            "parse_errors": [f"System Error: {str(e)}"]
        }).eq("id", file_id).execute()


def _process_gl_file(deal_id: str, file_id: str, content: bytes, filename: str):
    """
    Process a GL detail file:
    1. Parse Excel using IngestionService (header detection, column normalization)
    2. Batch-insert parsed transactions into gl_transactions
    3. Update the uploaded_files record with status and row count
    """
    supabase = get_supabase_admin_client()
    
    try:
        # Get organization_id from deal
        deal_res = supabase.table("deals").select("organization_id").eq("id", deal_id).single().execute()
        if not deal_res.data:
            raise ValueError(f"Deal {deal_id} not found")
        
        org_id = deal_res.data["organization_id"]
        
        # Parse the Excel file
        print(f"[GL Ingestion] Parsing file {filename} for deal {deal_id}...")
        transactions, stats = gl_service.process_excel_file(
            file_content=content,
            deal_id=deal_id,
            organization_id=org_id,
            filename=filename,
            validate=False  # Don't fail on trial balance for now
        )
        
        print(f"[GL Ingestion] Parsed {stats['rows_processed']} rows, skipped {stats['rows_skipped']}")
        
        if not transactions:
            supabase.table("uploaded_files").update({
                "status": "failed",
                "parse_errors": ["No valid transactions found in file"]
            }).eq("id", file_id).execute()
            return
        
        # Add file_id to each transaction
        for tx in transactions:
            tx["file_id"] = file_id
        
        # Batch insert into gl_transactions (batches of 500 to avoid payload limits)
        BATCH_SIZE = 500
        inserted_count = 0
        
        for i in range(0, len(transactions), BATCH_SIZE):
            batch = transactions[i:i + BATCH_SIZE]
            result = supabase.table("gl_transactions").insert(batch).execute()
            inserted_count += len(result.data) if result.data else 0
            print(f"[GL Ingestion] Inserted batch {i // BATCH_SIZE + 1}: {len(batch)} rows")
        
        # Update file status to completed
        supabase.table("uploaded_files").update({
            "status": "completed",
            "parse_errors": stats.get("parse_errors", [])[:20]  # Keep first 20 errors
        }).eq("id", file_id).execute()
        
        print(f"[GL Ingestion] Successfully ingested {inserted_count} transactions from {filename}")
        
    except Exception as e:
        print(f"[GL Ingestion] FAILED for {filename}: {e}")
        supabase.table("uploaded_files").update({
            "status": "failed",
            "parse_errors": [f"GL Processing Error: {str(e)}"]
        }).eq("id", file_id).execute()

@router.get(
    "/deals/{deal_id}/files",
    summary="List Uploaded Files",
    description="Get all files uploaded for a deal."
)
async def list_deal_files(deal_id: str = Path(...)):
    client = get_supabase_admin_client()
    res = client.table("uploaded_files").select("*").eq("deal_id", deal_id).order("created_at", desc=True).execute()
    return res.data


@router.delete(
    "/deals/{deal_id}/files/{file_id}",
    summary="Delete Uploaded File",
    description="Delete a file from storage and database."
)
async def delete_deal_file(
    deal_id: str = Path(...),
    file_id: str = Path(...)
):
    client = get_supabase_admin_client()
    
    # Get file to find storage path
    file_res = client.table("uploaded_files").select("storage_path").eq("id", file_id).eq("deal_id", deal_id).single().execute()
    
    if file_res.data:
        storage_path = file_res.data["storage_path"]
        try:
            client.storage.from_("deal_files").remove([storage_path])
        except Exception as e:
            print(f"Storage delete warning: {e}")

    # Delete from DB
    client.table("uploaded_files").delete().eq("id", file_id).execute()
    
    return {"message": "File deleted successfully"}
