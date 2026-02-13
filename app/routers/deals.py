"""
AceCPAs Backend - Deals Router
API endpoints for deal management and transaction operations.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Depends

from app.config import get_settings
from app.database import get_supabase_admin_client, DatabaseService
from app.models.schemas import (
    DealResponse,
    DealCreate,
    GLTransactionGridResponse,
    GLTransactionResponse,
    ApproveMappingsRequest,
    ApproveMappingsResponse,
    RunMapperRequest,
    RunMapperResponse,
    RunAuditorResponse,
    GenerateReportRequest,
    GenerateReportResponse,
    ErrorResponse
)
from app.workers.tasks import run_mapper_agent, run_auditor_agent, generate_excel_report

router = APIRouter()
settings = get_settings()


# ============================================
# Deal CRUD
# ============================================

@router.get(
    "",
    response_model=list[DealResponse],
    summary="List all deals",
    description="Get all deals accessible to the current user."
)
async def list_deals(
    org_id: Optional[str] = Query(None, description="Filter by organization ID"),
    status: Optional[str] = Query(None, description="Filter by status")
):
    """List all deals with optional filters."""
    client = get_supabase_admin_client()
    query = client.table("deals").select("*")
    
    if org_id:
        query = query.eq("org_id", org_id)
    if status:
        query = query.eq("status", status)
    
    result = query.order("created_at", desc=True).execute()
    return result.data


@router.get(
    "/{deal_id}",
    response_model=DealResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get deal by ID"
)
async def get_deal(deal_id: str):
    """Get a specific deal by ID."""
    client = get_supabase_admin_client()
    result = client.table("deals").select("*").eq("id", deal_id).single().execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    
    return result.data


@router.post(
    "",
    response_model=DealResponse,
    status_code=201,
    summary="Create a new deal"
)
async def create_deal(deal: DealCreate):
    """Create a new deal."""
    client = get_supabase_admin_client()
    result = client.table("deals").insert(deal.model_dump()).execute()
    return result.data[0]


# ============================================
# Transaction Grid (AG Grid)
# ============================================

@router.get(
    "/{deal_id}/grid",
    response_model=GLTransactionGridResponse,
    summary="Get transactions for AG Grid",
    description="Paginated transaction list with filtering support for AG Grid."
)
async def get_transaction_grid(
    deal_id: str,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(100, ge=10, le=1000, description="Items per page"),
    min_confidence: Optional[float] = Query(None, ge=0, le=1, description="Minimum confidence filter"),
    max_confidence: Optional[float] = Query(None, ge=0, le=1, description="Maximum confidence filter"),
    unmapped_only: bool = Query(False, description="Show only unmapped transactions"),
    unverified_only: bool = Query(False, description="Show only unverified transactions")
):
    """
    Get paginated transactions for AG Grid.
    
    Supports filtering by:
    - Confidence range (for flagging low-confidence mappings)
    - Unmapped status
    - Verification status
    """
    client = get_supabase_admin_client()
    
    # Build query
    query = client.table("gl_transactions").select(
        "*, master_coa(*)",
        count="exact"
    ).eq("deal_id", deal_id)
    
    # Apply filters
    if min_confidence is not None:
        query = query.gte("confidence", min_confidence)
    if max_confidence is not None:
        query = query.lte("confidence", max_confidence)
    if unmapped_only:
        query = query.is_("mapped_coa_id", "null")
    if unverified_only:
        query = query.eq("is_verified", False)
    
    # Calculate offset
    offset = (page - 1) * page_size
    
    # Execute with pagination
    result = query.order("row_number", desc=False).range(offset, offset + page_size - 1).execute()
    
    total_count = result.count or 0
    has_more = offset + len(result.data) < total_count
    
    # Transform response
    transactions = []
    for row in result.data:
        # Flatten master_coa into transaction
        coa = row.pop('master_coa', None)
        row['mapped_coa'] = coa
        transactions.append(row)
    
    return GLTransactionGridResponse(
        transactions=transactions,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_more=has_more
    )


# ============================================
# Mapping Approval
# ============================================

@router.post(
    "/{deal_id}/approve-map",
    response_model=ApproveMappingsResponse,
    summary="Approve transaction mappings",
    description="Mark selected transactions as verified. This turns them into 'Golden Data' for future vector searches."
)
async def approve_mappings(
    deal_id: str,
    request: ApproveMappingsRequest
):
    """
    Approve/verify transaction mappings.
    
    Verified transactions become part of the "Golden Data" corpus
    used for vector similarity matching in future uploads.
    """
    if not request.transaction_ids:
        raise HTTPException(status_code=400, detail="No transaction IDs provided")
    
    client = get_supabase_admin_client()
    
    # Convert UUIDs to strings for Supabase
    transaction_ids = [str(tid) for tid in request.transaction_ids]
    
    # Verify all transactions belong to this deal
    check_result = client.table("gl_transactions").select("id").eq(
        "deal_id", deal_id
    ).in_("id", transaction_ids).execute()
    
    found_ids = {row['id'] for row in check_result.data}
    invalid_ids = set(transaction_ids) - found_ids
    
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transaction IDs: {list(invalid_ids)}"
        )
    
    # Update transactions
    result = client.table("gl_transactions").update({
        "is_verified": True
    }).in_("id", transaction_ids).execute()
    
    return ApproveMappingsResponse(
        verified_count=len(result.data),
        message=f"Successfully verified {len(result.data)} transactions. These are now part of the Golden Data corpus."
    )


# ============================================
# AI Agents
# ============================================

@router.post(
    "/{deal_id}/run-mapper",
    response_model=RunMapperResponse,
    summary="Run mapper agent",
    description="Run the AI mapper agent on unmapped transactions."
)
async def run_mapper(
    deal_id: str,
    request: RunMapperRequest = RunMapperRequest()
):
    """
    Trigger the mapper agent to process unmapped transactions.
    
    The mapper uses:
    1. Vector similarity search on verified (golden) data
    2. LLM fallback for low-confidence matches
    """
    # Import here to avoid circular dependency
    from app.services.mapper_agent import MapperAgentService
    
    try:
        mapper = MapperAgentService()
        result = mapper.process_deal(
            deal_id=deal_id,
            reprocess_low_confidence=request.reprocess_low_confidence,
            confidence_threshold=request.confidence_threshold
        )
        
        return RunMapperResponse(
            processed_count=result.get('processed_count', 0),
            auto_mapped_count=result.get('auto_mapped_count', 0),
            llm_mapped_count=result.get('llm_mapped_count', 0),
            failed_count=result.get('failed_count', 0),
            message=f"Mapper completed. {result.get('processed_count', 0)} transactions processed."
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{deal_id}/run-auditor",
    response_model=RunAuditorResponse,
    summary="Run auditor agent",
    description="Run the auditor agent to detect anomalies and generate questions."
)
async def run_auditor(deal_id: str):
    """
    Trigger the auditor agent to scan for anomalies.
    
    The auditor:
    1. Flags transactions with suspicious keywords (Venmo, Cash, etc.)
    2. Flags large R&M expenses that may need CapEx treatment
    3. Generates professional client questions for flagged items
    """
    from app.services.auditor_agent import AuditorAgentService
    
    try:
        auditor = AuditorAgentService()
        result = auditor.process_deal(deal_id=deal_id)
        
        return RunAuditorResponse(
            flagged_count=result.get('flagged_count', 0),
            questions_generated=result.get('questions_generated', 0),
            message=f"Auditor completed. {result.get('flagged_count', 0)} items flagged."
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Reports
# ============================================

@router.post(
    "/{deal_id}/generate-report",
    response_model=GenerateReportResponse,
    summary="Generate Excel report",
    description="Generate a comprehensive Excel report for the deal."
)
async def generate_report(
    deal_id: str,
    request: GenerateReportRequest = GenerateReportRequest()
):
    """
    Trigger Excel report generation.
    
    The report includes:
    - Transaction listing with COA mappings
    - Summary by category
    - Open items list
    - Confidence scores
    """
    # TODO: Implement async report generation
    # For now, return a placeholder
    
    # Queue the task
    # generate_excel_report.delay(deal_id, request.model_dump())
    
    return GenerateReportResponse(
        report_url="/api/reports/placeholder",
        message="Report generation started. This feature is coming soon."
    )


# ============================================
# Statistics
# ============================================

@router.get(
    "/{deal_id}/stats",
    summary="Get deal statistics",
    description="Get summary statistics for a deal's transactions."
)
async def get_deal_stats(deal_id: str):
    """Get summary statistics for a deal."""
    client = get_supabase_admin_client()
    
    # Get counts using aggregates
    total_result = client.table("gl_transactions").select(
        "*", count="exact"
    ).eq("deal_id", deal_id).execute()
    
    mapped_result = client.table("gl_transactions").select(
        "*", count="exact"
    ).eq("deal_id", deal_id).not_.is_("mapped_coa_id", "null").execute()
    
    verified_result = client.table("gl_transactions").select(
        "*", count="exact"
    ).eq("deal_id", deal_id).eq("is_verified", True).execute()
    
    low_confidence_result = client.table("gl_transactions").select(
        "*", count="exact"
    ).eq("deal_id", deal_id).lt("confidence", 0.9).execute()
    
    open_items_result = client.table("open_items").select(
        "*", count="exact"
    ).eq("deal_id", deal_id).neq("status", "resolved").execute()
    
    return {
        "total_transactions": total_result.count or 0,
        "mapped_transactions": mapped_result.count or 0,
        "verified_transactions": verified_result.count or 0,
        "low_confidence_count": low_confidence_result.count or 0,
        "open_items_count": open_items_result.count or 0,
        "mapping_percentage": round(
            (mapped_result.count or 0) / (total_result.count or 1) * 100, 1
        ),
        "verification_percentage": round(
            (verified_result.count or 0) / (total_result.count or 1) * 100, 1
        )
    }
