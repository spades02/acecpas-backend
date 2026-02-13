import asyncio
from app.database import get_supabase_admin_client

async def init_missing_tables():
    print("Initializing missing tables...")
    client = get_supabase_admin_client()
    
    # SQL to create upload_jobs table
    sql = """
    CREATE TABLE IF NOT EXISTS upload_jobs (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
        file_name VARCHAR(255) NOT NULL,
        file_path VARCHAR(500),
        file_size_bytes BIGINT,
        status VARCHAR(50) DEFAULT 'pending',
        error_message TEXT,
        rows_processed INTEGER DEFAULT 0,
        rows_total INTEGER,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    
    # Supabase-py doesn't expose a raw 'query' or 'execute_sql' method easily 
    # via PostgREST unless we use specific RPCs.
    # But we can try to use the `rpc` if a helper exists, or sadly we might have to rely on the user.
    
    # Actually, standard PostgREST doesn't allow raw DDL injection security reasons.
    # So I cannot run CREATE TABLE from here unless you have a specific stored procedure for it.
    
    print("Checking if upload_jobs table exists...")
    try:
        # Try to select from it
        client.table("upload_jobs").select("id").limit(1).execute()
        print("Table 'upload_jobs' ALREADY EXISTS.")
    except Exception as e:
        print(f"Table 'upload_jobs' MISSING or inaccessible: {e}")
        print("\nPlease go to Supabase Dashboard -> SQL Editor and run the SQL below:\n")
        print(sql)

if __name__ == "__main__":
    asyncio.run(init_missing_tables())
