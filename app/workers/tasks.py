"""
AceCPAs Backend - Celery Tasks
Background tasks for file processing and AI agents.
"""
from datetime import datetime
from typing import Optional

from celery import shared_task

from app.database import get_supabase_admin_client, DatabaseService
from app.services.ingestion import IngestionService, TrialBalanceError, HeaderDetectionError


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_mapper_agent(
    self,
    deal_id: str,
    reprocess_low_confidence: bool = False,
    confidence_threshold: float = 0.9
):
    """
    Celery task to run the mapper agent on unmapped transactions.
    
    Args:
        deal_id: UUID of the deal
        reprocess_low_confidence: Whether to reprocess low-confidence mappings
        confidence_threshold: Threshold for low confidence
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
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "status": "failed",
            "error": str(e)
        }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_gl_file(
    self,
    job_id: str,
    deal_id: str,
    file_path: str,
    filename: str
):
    """
    Celery task to process a GL Excel file.
    
    Args:
        job_id: UUID of the upload job
        deal_id: UUID of the deal
        file_path: Path in Supabase Storage
        filename: Original filename
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
        # Generic error - retry if possible
        print(f"Job {job_id} failed: Generic Error - {e}")
        import traceback
        traceback.print_exc()
        client.table("files").update({
            "status": "failed",
            "error_message": f"Processing error: {str(e)}",
            "processed_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
        
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        
        return {
            "status": "failed",
            "error": "processing_error",
            "message": str(e)
        }


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_auditor_agent(self, deal_id: str):
    """
    Celery task to run the auditor agent for anomaly detection.
    
    Args:
        deal_id: UUID of the deal
    """
    from app.services.auditor_agent import AuditorAgentService
    
    try:
        auditor = AuditorAgentService()
        result = auditor.process_deal(deal_id=deal_id)
        return result
        
    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "status": "failed",
            "error": str(e)
        }


@shared_task
def generate_excel_report(deal_id: str, options: dict):
    """
    Celery task to generate Excel report for a deal.
    """
    # TODO: Implement Excel report generation
    pass
