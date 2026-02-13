from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class FileType(str, Enum):
    MONTHLY_PL = "monthly_pl"
    MONTHLY_BS = "monthly_bs"
    GL_DETAIL = "gl_detail"
    TRIAL_BALANCE = "trial_balance"

class UploadedFileResponse(BaseSchema):
    id: UUID
    deal_id: UUID
    file_type: str
    original_filename: str
    status: str
    parse_errors: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime

class AnomalyResponse(BaseSchema):
    id: UUID
    pl_line_item_id: UUID
    deal_id: UUID
    anomaly_type: str
    severity: str
    current_amount: Optional[Decimal] = None
    trailing_average: Optional[Decimal] = None
    variance_multiple: Optional[float] = None
    ai_summary: Optional[str] = None
    ai_detailed_analysis: Optional[str] = None
    is_addback_candidate: bool
    ai_confidence_score: Optional[float] = None
    created_at: datetime

class PLLineItemResponse(BaseSchema):
    id: UUID
    header_id: UUID
    deal_id: UUID
    line_name: str
    line_category: Optional[str] = None
    amount: Decimal
    display_order: Optional[int] = None
    indent_level: int
    is_subtotal: bool
    mapped_coa_id: Optional[UUID] = None
    gl_derived_amount: Optional[Decimal] = None
    gl_variance: Optional[Decimal] = None
    anomalies: Optional[List[AnomalyResponse]] = []

class MonthlyPLHeaderResponse(BaseSchema):
    id: UUID
    deal_id: UUID
    uploaded_file_id: UUID
    period_start: date
    period_end: date
    period_name: Optional[str] = None
    total_revenue: Optional[Decimal] = None
    gross_profit: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    ebitda_reported: Optional[Decimal] = None
    line_items: Optional[List[PLLineItemResponse]] = []

class AdjustmentCreate(BaseSchema):
    deal_id: UUID
    organization_id: UUID
    source: str
    source_ref_id: Optional[UUID] = None
    category: str
    description: str
    amount: Decimal
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    rationale: Optional[str] = None
    ai_analysis_text: Optional[str] = None

class AdjustmentResponse(AdjustmentCreate):
    id: UUID
    status: str
    created_by: Optional[UUID] = None
    approved_by: Optional[UUID] = None
    rejected_by: Optional[UUID] = None
    approval_notes: Optional[str] = None
    created_at: datetime
    approved_at: Optional[datetime] = None
