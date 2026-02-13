-- ============================================
-- Mapper Agent Tables
-- ============================================

-- Ensure helper functions exist from base schema
CREATE OR REPLACE FUNCTION get_user_org_ids()
RETURNS SETOF UUID AS $$
    SELECT org_id FROM user_organizations WHERE user_id = auth.uid()
$$ LANGUAGE SQL SECURITY DEFINER;


-- client_accounts
-- Aggregated unique accounts from gl_transactions that need mapping
CREATE TABLE IF NOT EXISTS client_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    original_account_string VARCHAR(500) NOT NULL, -- "Account Name | Description" key
    description TEXT,
    
    -- AI/Vector fields
    embedding vector(1536),
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(deal_id, original_account_string)
);

CREATE INDEX IF NOT EXISTS idx_client_accounts_deal_id ON client_accounts(deal_id);
-- Vector similarity index
CREATE INDEX IF NOT EXISTS idx_client_accounts_embedding ON client_accounts 
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);


-- account_mappings
-- Stores the mapping decision for a client_account
CREATE TABLE IF NOT EXISTS account_mappings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    client_account_id UUID NOT NULL REFERENCES client_accounts(id) ON DELETE CASCADE,
    
    -- The Mapping
    master_account_id UUID REFERENCES master_coa(id),
    
    -- AI Metadata
    confidence_score INTEGER, -- 0-100
    ai_reasoning TEXT,
    
    -- Workflow
    approval_status VARCHAR(50) DEFAULT 'yellow', -- 'green' (>90%), 'yellow' (<90%), 'approved', 'rejected'
    approved_by UUID REFERENCES auth.users(id),
    approved_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(client_account_id) -- One active mapping per account
);

CREATE INDEX IF NOT EXISTS idx_account_mappings_client_account_id ON account_mappings(client_account_id);
CREATE INDEX IF NOT EXISTS idx_account_mappings_approval_status ON account_mappings(approval_status);


-- golden_mappings
-- Training data / Knowledge Base from historical "Golden Data Sets"
CREATE TABLE IF NOT EXISTS golden_mappings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Input features (What we see in a raw GL)
    account_name VARCHAR(500),
    description TEXT,
    vendor_name VARCHAR(255),
    
    -- The "Truth" (What it maps to)
    correct_coa_id UUID REFERENCES master_coa(id), -- If we can link it
    correct_coa_name VARCHAR(255), -- Text backup if IDs don't match
    correct_category VARCHAR(100), -- High level category
    
    -- AI/Vector
    embedding vector(1536),
    
    -- Metadata
    source_deal VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_golden_mappings_embedding ON golden_mappings 
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- RLS Policies
ALTER TABLE client_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE golden_mappings ENABLE ROW LEVEL SECURITY;

-- client_accounts RLS
CREATE POLICY "Users can view client_accounts in their deals"
    ON client_accounts FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

CREATE POLICY "Users can insert client_accounts in their deals"
    ON client_accounts FOR INSERT
    WITH CHECK (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));
    
CREATE POLICY "Users can update client_accounts in their deals"
    ON client_accounts FOR UPDATE
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

-- account_mappings RLS
CREATE POLICY "Users can view account_mappings in their deals"
    ON account_mappings FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

CREATE POLICY "Users can insert account_mappings in their deals"
    ON account_mappings FOR INSERT
    WITH CHECK (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

CREATE POLICY "Users can update account_mappings in their deals"
    ON account_mappings FOR UPDATE
    USING (deal_id IN (SELECT id FROM deals WHERE org_id IN (SELECT get_user_org_ids())));

-- golden_mappings RLS (Everyone can read, only admins insert?)
-- For MVP, let's allow read for all authenticated users to leverage the knowledge base
CREATE POLICY "Users can read golden mappings"
    ON golden_mappings FOR SELECT
    USING (auth.role() = 'authenticated');

-- Vector Search RPC
CREATE OR REPLACE FUNCTION match_golden_mappings (
  query_embedding vector(1536),
  match_threshold float,
  match_count int
)
RETURNS TABLE (
  id UUID,
  account_name VARCHAR,
  description VARCHAR,
  vendor_name VARCHAR,
  correct_coa_name VARCHAR,
  correct_category VARCHAR,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    gm.id,
    gm.account_name,
    gm.description,
    gm.vendor_name,
    gm.correct_coa_name,
    gm.correct_category,
    1 - (gm.embedding <=> query_embedding) as similarity
  FROM golden_mappings gm
  WHERE 1 - (gm.embedding <=> query_embedding) > match_threshold
  ORDER BY gm.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
