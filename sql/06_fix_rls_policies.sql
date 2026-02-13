-- ============================================
-- 06_fix_rls_policies.sql (Revised)
-- Fixes 'org_id' vs 'organization_id' column mismatch in RLS policies
-- And enables RLS for new Phase 1 tables
-- Skips 'upload_jobs' which may not exist
-- ============================================

-- 1. DEALS POLICIES
DROP POLICY IF EXISTS "Users can view deals in their orgs" ON deals;
CREATE POLICY "Users can view deals in their orgs"
    ON deals FOR SELECT
    USING (organization_id IN (SELECT get_user_org_ids()));

DROP POLICY IF EXISTS "Users can insert deals in their orgs" ON deals;
CREATE POLICY "Users can insert deals in their orgs"
    ON deals FOR INSERT
    WITH CHECK (organization_id IN (SELECT get_user_org_ids()));

DROP POLICY IF EXISTS "Users can update deals in their orgs" ON deals;
CREATE POLICY "Users can update deals in their orgs"
    ON deals FOR UPDATE
    USING (organization_id IN (SELECT get_user_org_ids()));

DROP POLICY IF EXISTS "Users can delete deals in their orgs" ON deals;
CREATE POLICY "Users can delete deals in their orgs"
    ON deals FOR DELETE
    USING (organization_id IN (SELECT get_user_org_ids()));


-- 2. GL TRANSACTIONS POLICIES
DROP POLICY IF EXISTS "Users can view transactions in their deals" ON gl_transactions;
CREATE POLICY "Users can view transactions in their deals"
    ON gl_transactions FOR SELECT
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

DROP POLICY IF EXISTS "Users can insert transactions in their deals" ON gl_transactions;
CREATE POLICY "Users can insert transactions in their deals"
    ON gl_transactions FOR INSERT
    WITH CHECK (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

DROP POLICY IF EXISTS "Users can update transactions in their deals" ON gl_transactions;
CREATE POLICY "Users can update transactions in their deals"
    ON gl_transactions FOR UPDATE
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

DROP POLICY IF EXISTS "Users can delete transactions in their deals" ON gl_transactions;
CREATE POLICY "Users can delete transactions in their deals"
    ON gl_transactions FOR DELETE
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));


-- 3. OPEN ITEMS POLICIES
-- Only run if table exists (handled by IF EXISTS in DROP, but CREATE might fail if table missing.
-- Assuming open_items exists as per previous checks.)
DROP POLICY IF EXISTS "Users can view open items in their deals" ON open_items;
CREATE POLICY "Users can view open items in their deals"
    ON open_items FOR SELECT
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));

DROP POLICY IF EXISTS "Users can manage open items in their deals" ON open_items;
CREATE POLICY "Users can manage open items in their deals"
    ON open_items FOR ALL
    USING (deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    ));


-- 5. NEW PHASE 1 TABLES POLICIES (uploaded_files, etc.)

ALTER TABLE uploaded_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_pl_headers ENABLE ROW LEVEL SECURITY;
ALTER TABLE pl_line_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE anomalies ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustments ENABLE ROW LEVEL SECURITY;
ALTER TABLE adjustment_gl_links ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view files in their deals" ON uploaded_files;
CREATE POLICY "Users can view files in their deals"
    ON uploaded_files FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())));

DROP POLICY IF EXISTS "Users can insert files in their deals" ON uploaded_files;
CREATE POLICY "Users can insert files in their deals"
    ON uploaded_files FOR INSERT
    WITH CHECK (deal_id IN (SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())));

DROP POLICY IF EXISTS "Users can view PL headers in their deals" ON monthly_pl_headers;
CREATE POLICY "Users can view PL headers in their deals"
    ON monthly_pl_headers FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())));

DROP POLICY IF EXISTS "Users can view PL lines in their deals" ON pl_line_items;
CREATE POLICY "Users can view PL lines in their deals"
    ON pl_line_items FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())));

DROP POLICY IF EXISTS "Users can view anomalies in their deals" ON anomalies;
CREATE POLICY "Users can view anomalies in their deals"
    ON anomalies FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())));

DROP POLICY IF EXISTS "Users can view adjustments in their deals" ON adjustments;
CREATE POLICY "Users can view adjustments in their deals"
    ON adjustments FOR SELECT
    USING (deal_id IN (SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())));

DROP POLICY IF EXISTS "Users can manage adjustments in their deals" ON adjustments;
CREATE POLICY "Users can manage adjustments in their deals"
    ON adjustments FOR ALL
    USING (deal_id IN (SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())));

DROP POLICY IF EXISTS "Users can view adjustment links in their deals" ON adjustment_gl_links;
CREATE POLICY "Users can view adjustment links in their deals"
    ON adjustment_gl_links FOR SELECT
    USING (adjustment_id IN (SELECT id FROM adjustments WHERE deal_id IN (
        SELECT id FROM deals WHERE organization_id IN (SELECT get_user_org_ids())
    )));
