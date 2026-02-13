from sqlalchemy import Column, Integer, String, Boolean, Date, Float, ForeignKey, DECIMAL, Text, BigInteger, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.sql import func
import uuid
from .database import Base

class Organization(Base):
    __tablename__ = "organizations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    domain = Column(String, unique=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    deals = relationship("Deal", back_populates="organization")

class UserOrganization(Base):
    __tablename__ = "user_organizations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    role = Column(String, default="member")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class Deal(Base):
    __tablename__ = "deals"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    client_name = Column(String, nullable=False)
    status = Column(String, default="active")
    fy_end = Column(Date)
    industry = Column(String)
    notes = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    organization = relationship("Organization", back_populates="deals")
    
    # Relationships to new tables
    uploaded_files = relationship("UploadedFile", back_populates="deal", cascade="all, delete")
    monthly_pl_headers = relationship("MonthlyPLHeader", back_populates="deal", cascade="all, delete")
    pl_line_items = relationship("PLLineItem", back_populates="deal", cascade="all, delete")
    anomalies = relationship("Anomaly", back_populates="deal", cascade="all, delete")
    adjustments = relationship("Adjustment", back_populates="deal", cascade="all, delete")

class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    
    file_type = Column(String, nullable=False) # 'monthly_pl', etc.
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    file_size_bytes = Column(BigInteger)
    checksum = Column(String)
    
    status = Column(String, default="pending")
    parse_errors = Column(ARRAY(Text)) # Using ARRAY type for text[]
    
    uploaded_by = Column(UUID(as_uuid=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    deal = relationship("Deal", back_populates="uploaded_files")
    pl_headers = relationship("MonthlyPLHeader", back_populates="uploaded_file")

class MonthlyPLHeader(Base):
    __tablename__ = "monthly_pl_headers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False)
    uploaded_file_id = Column(UUID(as_uuid=True), ForeignKey("uploaded_files.id"), nullable=False)
    
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    period_name = Column(String)
    
    total_revenue = Column(DECIMAL(19, 4))
    gross_profit = Column(DECIMAL(19, 4))
    net_income = Column(DECIMAL(19, 4))
    ebitda_reported = Column(DECIMAL(19, 4))
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    
    deal = relationship("Deal", back_populates="monthly_pl_headers")
    uploaded_file = relationship("UploadedFile", back_populates="pl_headers")
    line_items = relationship("PLLineItem", back_populates="header", cascade="all, delete")

class PLLineItem(Base):
    __tablename__ = "pl_line_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    header_id = Column(UUID(as_uuid=True), ForeignKey("monthly_pl_headers.id"), nullable=False)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False)
    
    line_name = Column(String, nullable=False)
    line_category = Column(String)
    amount = Column(DECIMAL(19, 4), nullable=False)
    
    display_order = Column(Integer)
    indent_level = Column(Integer, default=0)
    is_subtotal = Column(Boolean, default=False)
    
    mapped_coa_id = Column(UUID(as_uuid=True)) # ForeignKey("master_coa.id") if mapped
    
    gl_derived_amount = Column(DECIMAL(19, 4))
    gl_variance = Column(DECIMAL(19, 4))
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    header = relationship("MonthlyPLHeader", back_populates="line_items")
    deal = relationship("Deal", back_populates="pl_line_items")
    anomalies = relationship("Anomaly", back_populates="line_item", cascade="all, delete")

class Anomaly(Base):
    __tablename__ = "anomalies"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pl_line_item_id = Column(UUID(as_uuid=True), ForeignKey("pl_line_items.id"), nullable=False)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False)
    
    anomaly_type = Column(String, nullable=False)
    severity = Column(String, default="medium")
    
    current_amount = Column(DECIMAL(19, 4))
    trailing_average = Column(DECIMAL(19, 4))
    variance_multiple = Column(Float)
    
    ai_summary = Column(Text)
    ai_detailed_analysis = Column(Text)
    is_addback_candidate = Column(Boolean, default=False)
    ai_confidence_score = Column(Float)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    
    line_item = relationship("PLLineItem", back_populates="anomalies")
    deal = relationship("Deal", back_populates="anomalies")

class Adjustment(Base):
    __tablename__ = "adjustments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    
    status = Column(String, default="draft")
    source = Column(String, nullable=False)
    source_ref_id = Column(UUID(as_uuid=True))
    
    category = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(DECIMAL(19, 4), nullable=False)
    period_start = Column(Date)
    period_end = Column(Date)
    
    rationale = Column(Text)
    ai_analysis_text = Column(Text)
    
    created_by = Column(UUID(as_uuid=True))
    approved_by = Column(UUID(as_uuid=True))
    rejected_by = Column(UUID(as_uuid=True))
    approval_notes = Column(Text)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
    approved_at = Column(TIMESTAMP(timezone=True))
    
    deal = relationship("Deal", back_populates="adjustments")
    gl_links = relationship("AdjustmentGLLink", back_populates="adjustment", cascade="all, delete")

class AdjustmentGLLink(Base):
    __tablename__ = "adjustment_gl_links"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    adjustment_id = Column(UUID(as_uuid=True), ForeignKey("adjustments.id"), nullable=False)
    gl_transaction_id = Column(UUID(as_uuid=True), nullable=False) # ForeignKey("gl_transactions.id")
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    
    adjustment = relationship("Adjustment", back_populates="gl_links")
