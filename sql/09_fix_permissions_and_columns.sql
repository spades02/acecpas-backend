-- ============================================
-- 09_fix_permissions_and_columns.sql
-- Updates get_user_org_ids function to include primary org from profiles.
-- Fixes RLS issues where user_organizations is empty.
-- ============================================

-- RECREATE get_user_org_ids to include fallback to profiles.organization_id
CREATE OR REPLACE FUNCTION get_user_org_ids()
RETURNS SETOF UUID AS $$
    SELECT org_id FROM user_organizations WHERE user_id = auth.uid()
    UNION
    SELECT organization_id FROM profiles WHERE auth0_sub = (
        SELECT raw_user_meta_data->>'sub' FROM auth.users WHERE id = auth.uid()
        -- OR maybe profiles.id matches auth.uid()? 
        -- If profiles.id matches auth.uid():
    ) OR id = auth.uid() -- Covering both bases if possible? No, stick to known link.
    -- If profiles table linked to auth.users via id?
    -- Let's assume profiles.id is NOT auth.uid() based on context "auth0_sub".
    -- But usually profiles.id is a UUID PK.
    
    -- SAFER: Just select organization_id from profiles where auth0_sub matches current user metadata?
    -- Accessing auth.jwt() -> sub is safer.
    
    -- However, let's keep it simple: Link via auth0_sub if stored in profiles.
    -- But wait, auth.users has 'raw_user_meta_data'.
    
    -- Simplify: Assuming profiles.id is linked to auth.users.id
    -- If not, we need a way to link.
    -- Let's try to select organization_id from profiles where auth0_sub = current user's sub claim.
    
    -- Query:
    -- SELECT organization_id FROM profiles WHERE auth0_sub = (auth.jwt() ->> 'sub');
$$ LANGUAGE SQL SECURITY DEFINER;

-- Actually, simpler version leveraging existing logic if profiles.id = auth.uid()
-- But since I saw 'auth0_sub' column usage in route.ts, likely profiles.id != auth.uid().
-- So I'll use the JWT claim approach.

CREATE OR REPLACE FUNCTION get_user_org_ids()
RETURNS SETOF UUID AS $$
    SELECT org_id FROM user_organizations WHERE user_id = auth.uid()
    UNION
    SELECT organization_id FROM profiles WHERE auth0_sub = (auth.jwt() ->> 'sub');
$$ LANGUAGE SQL SECURITY DEFINER;
