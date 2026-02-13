-- ============================================
-- 04_qoe_phase1_tables.sql
-- New tables for QoE Platform Specification v3 (Phase 1)
-- ============================================

-- Ensure helper functions exist from base schema
CREATE OR REPLACE FUNCTION get_user_org_ids()
RETURNS SETOF UUID AS $$
    SELECT org_id FROM user_organizations WHERE user_id = auth.uid()
$$ LANGUAGE SQL SECURITY DEFINER;


-- ============================================
-- TABLE: uploaded_files
-- Extends the concept of upload_jobs with more type awareness
-- ============================================
CREATE TABLE IF NOT EXISTS uploaded_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    file_type VARCHAR(50) NOT NULL, -- 'monthly_pl', 'monthly_bs', 'gl_detail', 'trial_balance'
    original_filename VARCHAR(255) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT,
    checksum VARCHAR(64), -- SHA256 for integrity
    
    -- Processing status
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    parse_errors TEXT[], -- Array of error strings
    
    uploaded_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_deal_id ON uploaded_files(deal_id);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_status ON uploaded_files(status);


-- ============================================
-- TABLE: monthly_pl_headers
-- Metadata for a parsed P&L file (one row per file/period)
-- ============================================
CREATE TABLE IF NOT EXISTS monthly_pl_headers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    uploaded_file_id UUID NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
    
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    period_name VARCHAR(50), -- 'Jan 2023', 'Q1 2023'
    
    -- Extracted Totals for validation
    total_revenue DECIMAL(19, 4),
    gross_profit DECIMAL(19, 4),
    net_income DECIMAL(19, 4),
    ebitda_reported DECIMAL(19, 4),
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_monthly_pl_headers_deal_period ON monthly_pl_headers(deal_id, period_start);


-- ============================================
-- TABLE: pl_line_items
-- The actual rows from the uploaded P&L
-- ============================================
CREATE TABLE IF NOT EXISTS pl_line_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    header_id UUID NOT NULL REFERENCES monthly_pl_headers(id) ON DELETE CASCADE,
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE, -- Denormalized for query speed
    
    -- Raw content
    line_name VARCHAR(255) NOT NULL,
    line_category VARCHAR(100), -- 'Revenue', 'COGS', 'OpEx', etc. (AI assigned on ingest)
    amount DECIMAL(19, 4) NOT NULL,
    
    -- Display formatting
    display_order INTEGER,
    indent_level INTEGER DEFAULT 0,
    is_subtotal BOOLEAN DEFAULT false,
    
    -- Mapping & Linkage
    mapped_coa_id UUID REFERENCES master_coa(id), -- If mapped to standard category
    
    -- Computed fields (populated after GL linkage)
    gl_derived_amount DECIMAL(19, 4),
    gl_variance DECIMAL(19, 4), -- amount - gl_derived_amount
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pl_line_items_header_id ON pl_line_items(header_id);
CREATE INDEX IF NOT EXISTS idx_pl_line_items_deal_category ON pl_line_items(deal_id, line_category);


-- ============================================
-- TABLE: anomalies
-- AI-detected variances in P&L line items
-- ============================================
CREATE TABLE IF NOT EXISTS anomalies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pl_line_item_id UUID NOT NULL REFERENCES pl_line_items(id) ON DELETE CASCADE,
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    
    -- Anomaly Details
    anomaly_type VARCHAR(50) NOT NULL, -- 'large_variance', 'new_account', 'missing_period'
    severity VARCHAR(20) DEFAULT 'medium', -- 'low', 'medium', 'high'
    
    -- Metrics
    current_amount DECIMAL(19, 4),
    trailing_average DECIMAL(19, 4),
    variance_multiple FLOAT, -- current / average
    
    -- AI Analysis
    ai_summary TEXT,
    ai_detailed_analysis TEXT,
    is_addback_candidate BOOLEAN DEFAULT false,
    ai_confidence_score FLOAT, -- 0-1
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_deal_id ON anomalies(deal_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_pl_line_id ON anomalies(pl_line_item_id);


-- ============================================
-- TABLE: adjustments
-- EBITDA Adjustments (Addbacks)
-- ============================================
CREATE TABLE IF NOT EXISTS adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Workflow
    status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'pending', 'approved', 'rejected'
    
    -- Source
    source VARCHAR(50) NOT NULL, -- 'ai_detected', 'drill_down', 'manual', 'excel_import'
    source_ref_id UUID, -- ID of whatever triggered this (anomaly_id, gl_transaction_id)
    
    -- Content
    category VARCHAR(100) NOT NULL, -- From Appendix A
    description TEXT NOT NULL,
    amount DECIMAL(19, 4) NOT NULL,
    period_start DATE,
    period_end DATE,
    
    -- Rationale
    rationale TEXT,
    ai_analysis_text TEXT,
    
    -- Approvals
    created_by UUID REFERENCES auth.users(id),
    approved_by UUID REFERENCES auth.users(id),
    rejected_by UUID REFERENCES auth.users(id),
    approval_notes TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    approved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_adjustments_deal_status ON adjustments(deal_id, status);


-- ============================================
-- TABLE: adjustment_gl_links
-- Many-to-many link between adjustments and GL transactions
-- ============================================
CREATE TABLE IF NOT EXISTS adjustment_gl_links (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    adjustment_id UUID NOT NULL REFERENCES adjustments(id) ON DELETE CASCADE,
    gl_transaction_id UUID NOT NULL REFERENCES gl_transactions(id) ON DELETE CASCADE,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(adjustment_id, gl_transaction_id)
);


-- ============================================
-- RLS POLICIES
-- ============================================

-- Enable RLS
ALTER TABLE uploaded_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_pl_headers ENABLE ROW LEVEL SECURITY;
ALTER TABLE pl_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE anomalies ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustments ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustment_gl_links ENABLE ROW LEVEL SECURITY;


-- 1. Uploaded Files
CREATE POLICY "Users can view files in their deals"
    ON uploaded_files FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

CREATE POLICY "Users can insert files in their deals"
    ON uploaded_files FOR INSERT
    WITH CHECK (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

-- 2. Monthly PL Headers
CREATE POLICY "Users can view PL headers in their deals"
    ON monthly_pl_headers FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

-- 3. PL Line Items
CREATE POLICY "Users can view PL lines in their deals"
    ON pl_line_items FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

-- 4. Anomalies
CREATE POLICY "Users can view anomalies in their deals"
    ON anomalies FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

-- 5. Adjustments
CREATE POLICY "Users can view adjustments in their deals"
    ON adjustments FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

CREATE POLICY "Users can manage adjustments in their deals"
    ON adjustments FOR ALL
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

-- 6. Adjustment GL Links
CREATE POLICY "Users can view adjustment links in their deals"
    ON adjustment_gl_links FOR SELECT
    USING (adjustment_id IN (SELECT id FROM adjustments WHERE deal_id IN (
        SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())
    )));

