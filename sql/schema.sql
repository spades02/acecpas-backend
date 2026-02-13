-- ============================================
-- AceCPAs MVP Database Schema
-- PostgreSQL 15 with pgvector extension
-- ============================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================
-- TABLE: organizations
-- Multi-tenant organization table
-- ============================================
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- TABLE: user_organizations (junction table)
-- Links Supabase Auth users to organizations
-- ============================================
CREATE TABLE user_organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role VARCHAR(50) DEFAULT 'member', -- 'admin', 'member', 'viewer'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, org_id)
);

-- ============================================
-- TABLE: deals
-- Financial deals/engagements per organization
-- ============================================
CREATE TABLE deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    client_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'active', -- 'active', 'completed', 'archived'
    fy_end DATE, -- Fiscal year end date
    industry VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_deals_org_id ON deals(org_id);
CREATE INDEX idx_deals_status ON deals(status);

-- ============================================
-- TABLE: master_coa
-- Master Chart of Accounts reference table
-- ============================================
CREATE TABLE master_coa (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category VARCHAR(100) NOT NULL, -- 'Revenue', 'COGS', 'Operating Expenses', etc.
    sub_category VARCHAR(100),
    account_name VARCHAR(255) NOT NULL,
    account_code VARCHAR(50),
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_master_coa_category ON master_coa(category);

-- ============================================
-- TABLE: gl_transactions
-- Core transaction table with embeddings
-- ============================================
CREATE TABLE gl_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    
    -- Raw data from Excel upload
    raw_date DATE,
    raw_account VARCHAR(500),
    raw_desc TEXT,
    vendor VARCHAR(255),
    amount DECIMAL(19, 4) NOT NULL, -- CRITICAL: Never use Float for financial data
    
    -- Mapping fields
    mapped_coa_id UUID REFERENCES master_coa(id),
    confidence FLOAT, -- Similarity score from vector search or LLM
    is_verified BOOLEAN DEFAULT false, -- True when user approves mapping
    
    -- AI/Vector fields
    embedding vector(1536), -- OpenAI text-embedding-3-small dimension
    
    -- Metadata
    source_file VARCHAR(255),
    row_number INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_gl_transactions_deal_id ON gl_transactions(deal_id);
CREATE INDEX idx_gl_transactions_mapped_coa_id ON gl_transactions(mapped_coa_id);
CREATE INDEX idx_gl_transactions_confidence ON gl_transactions(confidence);
CREATE INDEX idx_gl_transactions_is_verified ON gl_transactions(is_verified);

-- Vector similarity index for fast searches
CREATE INDEX idx_gl_transactions_embedding ON gl_transactions 
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================
-- TABLE: open_items
-- Audit questions and client responses
-- ============================================
CREATE TABLE open_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    transaction_id UUID REFERENCES gl_transactions(id) ON DELETE SET NULL,
    
    -- Question details
    flag_reason VARCHAR(100), -- 'keyword_flag', 'capex_threshold', 'low_confidence', etc.
    question_text TEXT NOT NULL,
    
    -- Response tracking
    client_response TEXT,
    status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'sent', 'responded', 'resolved'
    
    -- Metadata
    sent_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES auth.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_open_items_deal_id ON open_items(deal_id);
CREATE INDEX idx_open_items_status ON open_items(status);

-- ============================================
-- TABLE: upload_jobs
-- Track async file processing jobs
-- ============================================
CREATE TABLE upload_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500),
    file_size_bytes BIGINT,
    
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    error_message TEXT,
    
    rows_processed INTEGER DEFAULT 0,
    rows_total INTEGER,
    
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_upload_jobs_deal_id ON upload_jobs(deal_id);
CREATE INDEX idx_upload_jobs_status ON upload_jobs(status);

-- ============================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- Ensures multi-tenant data isolation
-- ============================================

-- Enable RLS on all tables
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE gl_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE open_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE upload_jobs ENABLE ROW LEVEL SECURITY;

-- Helper function to get user's organization IDs
CREATE OR REPLACE FUNCTION get_user_org_ids()
RETURNS SETOF UUID AS $$
    SELECT org_id FROM user_organizations WHERE user_id = auth.uid()
$$ LANGUAGE SQL SECURITY DEFINER;

-- Organizations: Users can only see orgs they belong to
CREATE POLICY "Users can view their organizations"
    ON organizations FOR SELECT
    USING (id IN (SELECT get_user_org_ids()));

CREATE POLICY "Users can insert organizations"
    ON organizations FOR INSERT
    WITH CHECK (true); -- Allow creating new orgs, then add user_organizations entry

-- User Organizations: Users can only see their own memberships
CREATE POLICY "Users can view their memberships"
    ON user_organizations FOR SELECT
    USING (user_id = auth.uid());

CREATE POLICY "Users can manage memberships in their orgs"
    ON user_organizations FOR ALL
    USING (org_id IN (SELECT get_user_org_ids()));

-- Deals: Users can only access deals in their organizations
CREATE POLICY "Users can view deals in their orgs"
    ON deals FOR SELECT
    USING (organization_id IN (SELECT get_user_org_ids()));

CREATE POLICY "Users can insert deals in their orgs"
    ON deals FOR INSERT
    WITH CHECK (organization_id IN (SELECT get_user_org_ids()));

CREATE POLICY "Users can update deals in their orgs"
    ON deals FOR UPDATE
    USING (organization_id IN (SELECT get_user_org_ids()));

CREATE POLICY "Users can delete deals in their orgs"
    ON deals FOR DELETE
    USING (organization_id IN (SELECT get_user_org_ids()));

-- GL Transactions: Scoped via deals.organization_id
CREATE POLICY "Users can view transactions in their deals"
    ON gl_transactions FOR SELECT
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

CREATE POLICY "Users can insert transactions in their deals"
    ON gl_transactions FOR INSERT
    WITH CHECK (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

CREATE POLICY "Users can update transactions in their deals"
    ON gl_transactions FOR UPDATE
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

CREATE POLICY "Users can delete transactions in their deals"
    ON gl_transactions FOR DELETE
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

-- Open Items: Scoped via deals.organization_id
CREATE POLICY "Users can view open items in their deals"
    ON open_items FOR SELECT
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

CREATE POLICY "Users can manage open items in their deals"
    ON open_items FOR ALL
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

-- Upload Jobs: Scoped via deals.organization_id
CREATE POLICY "Users can view upload jobs in their deals"
    ON upload_jobs FOR SELECT
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

CREATE POLICY "Users can manage upload jobs in their deals"
    ON upload_jobs FOR ALL
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

-- ============================================
-- SEED DATA: Master Chart of Accounts
-- ============================================
INSERT INTO master_coa (category, sub_category, account_name) VALUES
-- Revenue
('Revenue', 'Sales', 'Product Sales'),
('Revenue', 'Sales', 'Service Revenue'),
('Revenue', 'Sales', 'Consulting Revenue'),
('Revenue', 'Other Income', 'Interest Income'),
('Revenue', 'Other Income', 'Rental Income'),

-- Cost of Goods Sold
('COGS', 'Direct Costs', 'Cost of Goods Sold'),
('COGS', 'Direct Costs', 'Direct Labor'),
('COGS', 'Direct Costs', 'Materials'),
('COGS', 'Direct Costs', 'Freight In'),

-- Operating Expenses
('Operating Expenses', 'Payroll', 'Salaries & Wages'),
('Operating Expenses', 'Payroll', 'Payroll Taxes'),
('Operating Expenses', 'Payroll', 'Employee Benefits'),
('Operating Expenses', 'Payroll', 'Contractor Payments'),

('Operating Expenses', 'Facilities', 'Rent Expense'),
('Operating Expenses', 'Facilities', 'Utilities'),
('Operating Expenses', 'Facilities', 'Repairs & Maintenance'),
('Operating Expenses', 'Facilities', 'Security'),

('Operating Expenses', 'Marketing', 'Advertising'),
('Operating Expenses', 'Marketing', 'Marketing Software'),
('Operating Expenses', 'Marketing', 'Events & Sponsorships'),

('Operating Expenses', 'Technology', 'Software Subscriptions'),
('Operating Expenses', 'Technology', 'Cloud Services'),
('Operating Expenses', 'Technology', 'IT Equipment'),

('Operating Expenses', 'Professional Services', 'Legal Fees'),
('Operating Expenses', 'Professional Services', 'Accounting Fees'),
('Operating Expenses', 'Professional Services', 'Consulting Fees'),

('Operating Expenses', 'Travel', 'Travel - Air'),
('Operating Expenses', 'Travel', 'Travel - Lodging'),
('Operating Expenses', 'Travel', 'Travel - Meals'),
('Operating Expenses', 'Travel', 'Mileage Reimbursement'),

('Operating Expenses', 'Office', 'Office Supplies'),
('Operating Expenses', 'Office', 'Postage & Shipping'),
('Operating Expenses', 'Office', 'Printing'),

('Operating Expenses', 'Insurance', 'General Liability Insurance'),
('Operating Expenses', 'Insurance', 'Professional Liability Insurance'),
('Operating Expenses', 'Insurance', 'Health Insurance'),

('Operating Expenses', 'Depreciation', 'Depreciation Expense'),
('Operating Expenses', 'Amortization', 'Amortization Expense'),

-- Other Expenses
('Other Expenses', 'Interest', 'Interest Expense'),
('Other Expenses', 'Bank Fees', 'Bank Service Charges'),
('Other Expenses', 'Taxes', 'Income Tax Expense'),
('Other Expenses', 'Taxes', 'Property Tax'),

-- Assets
('Assets', 'Current Assets', 'Cash'),
('Assets', 'Current Assets', 'Accounts Receivable'),
('Assets', 'Current Assets', 'Inventory'),
('Assets', 'Current Assets', 'Prepaid Expenses'),
('Assets', 'Fixed Assets', 'Property & Equipment'),
('Assets', 'Fixed Assets', 'Accumulated Depreciation'),

-- Liabilities
('Liabilities', 'Current Liabilities', 'Accounts Payable'),
('Liabilities', 'Current Liabilities', 'Accrued Expenses'),
('Liabilities', 'Current Liabilities', 'Deferred Revenue'),
('Liabilities', 'Long-term Liabilities', 'Notes Payable'),
('Liabilities', 'Long-term Liabilities', 'Mortgage Payable'),

-- Equity
('Equity', 'Owners Equity', 'Common Stock'),
('Equity', 'Owners Equity', 'Retained Earnings'),
('Equity', 'Owners Equity', 'Owner Draws');

-- ============================================
-- TRIGGERS: Auto-update updated_at timestamps
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_deals_updated_at
    BEFORE UPDATE ON deals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_gl_transactions_updated_at
    BEFORE UPDATE ON gl_transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_open_items_updated_at
    BEFORE UPDATE ON open_items
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
