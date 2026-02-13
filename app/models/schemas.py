"""
AceCPAs Backend - Pydantic Models
Request/Response schemas for API endpoints.
"""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# ============================================
# Enums
# ============================================

class DealStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class UploadJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class OpenItemStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    RESPONDED = "responded"
    RESOLVED = "resolved"


# ============================================
# Base Models
# ============================================

class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    model_config = ConfigDict(from_attributes=True)


# ============================================
# Organization Schemas
# ============================================

class OrganizationBase(BaseSchema):
    name: str
    domain: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationResponse(OrganizationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


# ============================================
# Deal Schemas
# ============================================

class DealBase(BaseSchema):
    client_name: str
    status: DealStatus = DealStatus.ACTIVE
    fy_end: Optional[date] = None
    industry: Optional[str] = None
    notes: Optional[str] = None


class DealCreate(DealBase):
    org_id: UUID


class DealResponse(DealBase):
    id: UUID
    org_id: UUID
    created_at: datetime
    updated_at: datetime


# ============================================
# Master COA Schemas
# ============================================

class MasterCOABase(BaseSchema):
    category: str
    sub_category: Optional[str] = None
    account_name: str
    account_code: Optional[str] = None
    description: Optional[str] = None


class MasterCOAResponse(MasterCOABase):
    id: UUID
    is_active: bool
    created_at: datetime


# ============================================
# GL Transaction Schemas
# ============================================

class GLTransactionBase(BaseSchema):
    raw_date: Optional[date] = None
    raw_account: Optional[str] = None
    raw_desc: Optional[str] = None
    vendor: Optional[str] = None
    amount: Decimal = Field(..., decimal_places=4)


class GLTransactionCreate(GLTransactionBase):
    deal_id: UUID
    source_file: Optional[str] = None
    row_number: Optional[int] = None


class GLTransactionResponse(GLTransactionBase):
    id: UUID
    deal_id: UUID
    mapped_coa_id: Optional[UUID] = None
    mapped_coa: Optional[MasterCOAResponse] = None
    confidence: Optional[float] = None
    is_verified: bool = False
    source_file: Optional[str] = None
    row_number: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class GLTransactionGridResponse(BaseSchema):
    """Response for AG Grid with pagination."""
    transactions: List[GLTransactionResponse]
    total_count: int
    page: int
    page_size: int
    has_more: bool


# ============================================
# Open Item Schemas
# ============================================

class OpenItemBase(BaseSchema):
    flag_reason: Optional[str] = None
    question_text: str


class OpenItemCreate(OpenItemBase):
    deal_id: UUID
    transaction_id: Optional[UUID] = None


class OpenItemResponse(OpenItemBase):
    id: UUID
    deal_id: UUID
    transaction_id: Optional[UUID] = None
    transaction: Optional[GLTransactionResponse] = None
    client_response: Optional[str] = None
    status: OpenItemStatus = OpenItemStatus.DRAFT
    sent_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class OpenItemUpdateRequest(BaseSchema):
    """For updating open item status or adding response."""
    status: Optional[OpenItemStatus] = None
    client_response: Optional[str] = None


# ============================================
# Upload Job Schemas
# ============================================

class UploadJobCreate(BaseSchema):
    deal_id: UUID
    file_name: str
    file_path: str
    file_size_bytes: Optional[int] = None


class UploadJobResponse(BaseSchema):
    id: UUID
    deal_id: UUID
    file_name: str
    status: UploadJobStatus
    error_message: Optional[str] = None
    rows_processed: int
    rows_total: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


# ============================================
# Request/Response for API Endpoints
# ============================================

class FileUploadResponse(BaseSchema):
    """Response from file upload endpoint."""
    job_id: UUID
    message: str = "File upload started"


class ApproveMappingsRequest(BaseSchema):
    """Request to approve/verify transaction mappings."""
    transaction_ids: List[UUID]


class ApproveMappingsResponse(BaseSchema):
    """Response from approve mappings endpoint."""
    verified_count: int
    message: str


class GenerateReportRequest(BaseSchema):
    """Request to generate Excel report."""
    include_unmapped: bool = True
    include_low_confidence: bool = True
    confidence_threshold: float = 0.9


class GenerateReportResponse(BaseSchema):
    """Response from report generation."""
    report_url: str
    message: str


class RunAuditorRequest(BaseSchema):
    """Request to run auditor agent on a deal."""
    pass  # No additional params needed for now


class RunAuditorResponse(BaseSchema):
    """Response from auditor agent."""
    flagged_count: int
    questions_generated: int
    message: str


class RunMapperRequest(BaseSchema):
    """Request to run mapper agent on unmapped transactions."""
    reprocess_low_confidence: bool = False
    confidence_threshold: float = 0.9


class RunMapperResponse(BaseSchema):
    """Response from mapper agent."""
    processed_count: int
    auto_mapped_count: int
    llm_mapped_count: int
    failed_count: int
    message: str


# ============================================
# Error Response
# ============================================

class ErrorResponse(BaseSchema):
    """Standard error response."""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None


# ============================================
# Consolidation Schemas
# ============================================

class ConsolidationRequest(BaseSchema):
    """Request for consolidated P&L."""
    deal_ids: List[UUID]
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    period_type: str = "month" # month, quarter, year
    
class ConsolidatedValue(BaseSchema):
    """Value for a specific deal in the consolidation."""
    deal_id: UUID
    amount: Decimal

class ConsolidatedLineItem(BaseSchema):
    """A single line item in the consolidated view."""
    category: str
    subcategory: Optional[str] = None
    account_name: str
    deal_values: List[ConsolidatedValue]
    total_amount: Decimal

class ConsolidationDealInfo(BaseSchema):
    """Lightweight deal info for consolidation (avoids strict validation)."""
    id: UUID
    client_name: str
    status: Optional[str] = None
    industry: Optional[str] = None

class ConsolidationResponse(BaseSchema):
    """Response for consolidation endpoint."""
    line_items: List[ConsolidatedLineItem]
    deals: List[ConsolidationDealInfo]


# ============================================
# EBITDA Bridge Schemas
# ============================================

class EBITDABridgeRequest(BaseSchema):
    """Request for EBITDA Bridge analysis."""
    deal_id: UUID
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class BridgeStep(BaseSchema):
    """A single step/bar in the EBITDA waterfall."""
    label: str
    value: Decimal
    running_total: Decimal
    step_type: str  # 'total', 'addition', 'subtraction'
    category: Optional[str] = None

class EBITDABridgeResponse(BaseSchema):
    """Response for EBITDA Bridge."""
    deal_id: UUID
    client_name: str
    steps: List[BridgeStep]
    revenue: Decimal
    gross_profit: Decimal
    ebitda: Decimal
    net_income: Decimal


