-- ============================================
-- Vector Search Function for Mapper Agent
-- Add this after running the main schema.sql
-- ============================================

-- Function to find similar transactions using vector similarity
CREATE OR REPLACE FUNCTION match_transactions(
    query_embedding vector(1536),
    match_count int DEFAULT 5,
    filter_verified boolean DEFAULT true
)
RETURNS TABLE (
    id uuid,
    deal_id uuid,
    raw_account text,
    raw_desc text,
    vendor text,
    amount decimal,
    mapped_coa_id uuid,
    coa_name text,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.id,
        t.deal_id,
        t.raw_account,
        t.raw_desc,
        t.vendor,
        t.amount,
        t.mapped_coa_id,
        c.account_name as coa_name,
        1 - (t.embedding <=> query_embedding) as similarity
    FROM gl_transactions t
    LEFT JOIN master_coa c ON t.mapped_coa_id = c.id
    WHERE 
        t.embedding IS NOT NULL
        AND t.mapped_coa_id IS NOT NULL
        AND (NOT filter_verified OR t.is_verified = true)
    ORDER BY t.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION match_transactions TO authenticated;
GRANT EXECUTE ON FUNCTION match_transactions TO service_role;


-- ============================================
-- Supabase Storage Bucket Setup
-- Run this in Supabase SQL Editor
-- ============================================

-- Create the uploads bucket if it doesn't exist
INSERT INTO storage.buckets (id, name, public)
VALUES ('uploads', 'uploads', false)
ON CONFLICT (id) DO NOTHING;

-- RLS Policy for uploads bucket
CREATE POLICY "Users can upload files to their deals"
ON storage.objects FOR INSERT
WITH CHECK (
    bucket_id = 'uploads' AND
    -- Verify the deal belongs to user's org
    (storage.foldername(name))[2] IN (
        SELECT d.id::text 
        FROM deals d 
        WHERE d.org_id IN (SELECT get_user_org_ids())
    )
);

CREATE POLICY "Users can read files from their deals"
ON storage.objects FOR SELECT
USING (
    bucket_id = 'uploads' AND
    (storage.foldername(name))[2] IN (
        SELECT d.id::text 
        FROM deals d 
        WHERE d.org_id IN (SELECT get_user_org_ids())
    )
);

-- Service role can access all files
CREATE POLICY "Service role has full access"
ON storage.objects FOR ALL
USING (auth.role() = 'service_role');
