"""
AceCPAs Backend - Mapper Router
Endpoints for triggering account extraction and AI-powered COA mapping.
"""
import logging
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.database import get_supabase_admin_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mapper", tags=["Mapper"])


class MapperTriggerRequest(BaseModel):
    """Request body for triggering the mapper."""
    deal_id: str
    organization_id: str
    reprocess: bool = False  # Whether to re-map accounts that already have mappings


class MapperResponse(BaseModel):
    """Response from mapper operations."""
    success: bool
    message: str
    extracted_count: int = 0
    mapped_count: int = 0


def _run_mapper_background(deal_id: str, reprocess: bool = False):
    """Background task that runs the mapper agent."""
    try:
        from app.services.mapper_agent import MapperAgentService
        mapper = MapperAgentService()
        result = mapper.process_deal(deal_id, reprocess_low_confidence=reprocess)
        logger.info(f"Mapper completed for deal {deal_id}: {result}")
    except Exception as e:
        logger.error(f"Mapper background task failed for deal {deal_id}: {e}")


@router.post("/extract", response_model=MapperResponse)
async def extract_accounts(body: MapperTriggerRequest):
    """
    Step 1: Extract unique accounts from GL transactions for a deal.
    This is a synchronous operation that scans gl_transactions and
    populates the client_accounts table.
    """
    try:
        from app.services.mapper_agent import MapperAgentService
        mapper = MapperAgentService()
        count = mapper.extract_unique_accounts(body.deal_id)
        
        return MapperResponse(
            success=True,
            message=f"Extracted {count} unique accounts from GL transactions.",
            extracted_count=count
        )
    except Exception as e:
        logger.error(f"Account extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run", response_model=MapperResponse)
async def run_mapper(body: MapperTriggerRequest, background_tasks: BackgroundTasks):
    """
    Step 2: Run the full mapper pipeline (extract + AI map) in the background.
    Returns immediately with a success message.
    The mapping runs asynchronously using BackgroundTasks.
    """
    try:
        # Quick validation: does the deal exist and have GL data?
        client = get_supabase_admin_client()
        
        deal_check = client.table("deals").select("id").eq("id", body.deal_id).execute()
        if not deal_check.data:
            raise HTTPException(status_code=404, detail="Deal not found")
        
        gl_check = client.table("gl_transactions").select("id").eq("deal_id", body.deal_id).limit(1).execute()
        if not gl_check.data:
            raise HTTPException(
                status_code=400, 
                detail="No GL transactions found for this deal. Upload a GL file first."
            )
        
        # Schedule the mapper to run in the background
        background_tasks.add_task(_run_mapper_background, body.deal_id, body.reprocess)
        
        return MapperResponse(
            success=True,
            message="Mapper started. Accounts will be extracted and mapped in the background.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start mapper: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_mapper_status(deal_id: str = Query(..., description="Deal ID")):
    """
    Get the current mapping status for a deal.
    Returns counts of mapped, unmapped, and needs-review accounts.
    """
    try:
        client = get_supabase_admin_client()
        
        # Get all client accounts for this deal
        accounts_res = client.table("client_accounts") \
            .select("id, account_mappings(id, confidence_score, approval_status)") \
            .eq("deal_id", deal_id) \
            .execute()
        
        accounts = accounts_res.data or []
        
        total = len(accounts)
        approved = 0
        needs_review = 0
        unmapped = 0
        
        for acc in accounts:
            mappings = acc.get("account_mappings", [])
            if mappings:
                mapping = mappings[0]
                status = mapping.get("approval_status", "red")
                if status == "green":
                    approved += 1
                elif status == "yellow":
                    needs_review += 1
                else:
                    unmapped += 1
            else:
                unmapped += 1
        
        return {
            "success": True,
            "deal_id": deal_id,
            "total_accounts": total,
            "approved": approved,
            "needs_review": needs_review,
            "unmapped": unmapped,
            "is_complete": unmapped == 0 and needs_review == 0 and total > 0,
            "progress_pct": round((approved / total) * 100) if total > 0 else 0
        }
        
    except Exception as e:
        logger.error(f"Failed to get mapper status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
