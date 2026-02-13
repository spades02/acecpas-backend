"""
AceCPAs Backend - Synchronous Tasks (Free Tier Optimized)
Background tasks for file processing and AI agents.
Modified to run synchronously without Celery/Redis for simplified deployment.
"""
from datetime import datetime
from typing import Optional

# Removed Celery imports for Free Tier compatibility
# from celery import shared_task

from app.database import get_supabase_admin_client, DatabaseService
from app.services.ingestion import IngestionService, TrialBalanceError, HeaderDetectionError


def run_mapper_agent(
    deal_id: str,
    reprocess_low_confidence: bool = False,
    confidence_threshold: float = 0.9
):
    """
    Run the mapper agent on unmapped transactions.
    """
    from app.services.mapper_agent import MapperAgentService
    
    try:
        mapper = MapperAgentService()
        result = mapper.process_deal(
            deal_id=deal_id,
            reprocess_low_confidence=reprocess_low_confidence,
            confidence_threshold=confidence_threshold
        )
        return result
        
    except Exception as e:
        print(f"Mapper Agent failed: {e}")
        return {
            "status": "failed",
            "error": str(e)
        }


def process_gl_file(
    job_id: str,
    deal_id: str,
    file_path: str,
    filename: str
):
    """
    Process a GL Excel file synchronously.
    """
    client = get_supabase_admin_client()
    db = DatabaseService(client)
    
    try:
        # Update job status to processing
        client.table("files").update({
            "status": "processing",
        }).eq("id", job_id).execute()
        
        # Download file from Supabase Storage
        storage = client.storage.from_("deal_files") # Correct bucket
        file_content = storage.download(file_path)
        
        # Fetch organization_id from deal for RLS/Schema compliance
        deal_res = client.table("deals").select("organization_id").eq("id", deal_id).single().execute()
        if not deal_res.data:
            raise Exception(f"Deal {deal_id} not found")
        organization_id = deal_res.data['organization_id']

        # Process the file
        ingestion = IngestionService()
        # validate=False allows unbalanced files for MVP
        transactions, stats = ingestion.process_excel_file(
            file_content=file_content,
            deal_id=deal_id,
            organization_id=organization_id,
            filename=filename,
            validate=False
        )
        
        # Bulk insert transactions
        if transactions:
            # Add file_id to transactions (deal_id and org_id added in ingestion)
            for t in transactions:
                t['file_id'] = job_id
            
            # Insert in batches of 500
            batch_size = 500
            for i in range(0, len(transactions), batch_size):
                batch = transactions[i:i + batch_size]
                client.table("gl_transactions").insert(batch).execute()
        
        # --- TRIGGER MAPPER AGENT ---
        # Run mapper agent to extract and map accounts
        print(f"Triggering Mapper Agent for deal {deal_id}")
        run_mapper_agent(deal_id=deal_id)

        # Update job status to completed
        client.table("files").update({
            "status": "completed",
            "processed_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
        
        return {
            "status": "success",
            "job_id": job_id,
            "rows_processed": stats['rows_processed'],
            "stats": stats
        }
        
    except TrialBalanceError as e:
        # Trial balance failed - mark as failed with specific error
        print(f"Job {job_id} failed: Trial Balance Error - {e}")
        client.table("files").update({
            "status": "failed",
            "error_message": str(e),
            "processed_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
        
        return {
            "status": "failed",
            "error": "trial_balance_error",
            "message": str(e)
        }
        
    except HeaderDetectionError as e:
        # Could not detect header - mark as failed
        print(f"Job {job_id} failed: Header Detection Error - {e}")
        client.table("files").update({
            "status": "failed",
            "error_message": str(e),
            "processed_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
        
        return {
            "status": "failed",
            "error": "header_detection_error",
            "message": str(e)
        }
        
    except Exception as e:
        # Generic error
        print(f"Job {job_id} failed: Generic Error - {e}")
        import traceback
        traceback.print_exc()
        client.table("files").update({
            "status": "failed",
            "error_message": f"Processing error: {str(e)}",
            "processed_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
        
        return {
            "status": "failed",
            "error": "processing_error",
            "message": str(e)
        }


def run_auditor_agent(deal_id: str):
    """
    Run the auditor agent for anomaly detection.
    """
    from app.services.auditor_agent import AuditorAgentService
    
    try:
        auditor = AuditorAgentService()
        result = auditor.process_deal(deal_id=deal_id)
        return result
        
    except Exception as e:
        print(f"Auditor Agent failed: {e}")
        return {
            "status": "failed",
            "error": str(e)
        }


def generate_excel_report(deal_id: str, options: dict):
    """
    Generate Excel report for a deal.
    """
    # TODO: Implement Excel report generation
    pass
