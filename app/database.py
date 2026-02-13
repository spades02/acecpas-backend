"""
AceCPAs Backend - Database Module
Supabase client initialization and utilities.
"""
from functools import lru_cache
from typing import Optional
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions
from app.config import get_settings


@lru_cache()
def get_supabase_client() -> Client:
    """
    Get Supabase client with anon key (respects RLS policies).
    Use this for user-scoped operations.
    """
    settings = get_settings()
    print(f"DEBUG: init anon client: {settings.supabase_url}")
    return create_client(
        settings.supabase_url,
        settings.supabase_key
    )


@lru_cache()
def get_supabase_admin_client() -> Client:
    """
    Get Supabase client with service role key (bypasses RLS).
    Use this for system operations like async tasks.
    CAUTION: Always scope queries by org_id manually!
    """
    settings = get_settings()
    print(f"DEBUG: init admin client: {settings.supabase_url}")
    return create_client(
        settings.supabase_url,
        settings.supabase_service_key
    )


def get_supabase_client_with_token(access_token: str) -> Client:
    """
    Get Supabase client authenticated with user's JWT token.
    This ensures RLS policies are applied for this specific user.
    """
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_key)
    client.auth.set_session(access_token, "")
    return client


class DatabaseService:
    """
    Service class for common database operations.
    Wraps Supabase client with typed methods.
    """
    
    def __init__(self, client: Optional[Client] = None):
        self.client = client or get_supabase_client()
    
    # Organizations
    async def get_organization(self, org_id: str) -> dict:
        result = self.client.table("organizations").select("*").eq("id", org_id).single().execute()
        return result.data
    
    # Deals
    async def get_deal(self, deal_id: str) -> dict:
        result = self.client.table("deals").select("*").eq("id", deal_id).single().execute()
        return result.data
    
    async def get_deals_for_org(self, org_id: str) -> list[dict]:
        result = self.client.table("deals").select("*").eq("org_id", org_id).execute()
        return result.data
    
    # GL Transactions
    async def get_transactions_for_deal(
        self, 
        deal_id: str, 
        limit: int = 100, 
        offset: int = 0,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None
    ) -> list[dict]:
        query = self.client.table("gl_transactions").select(
            "*, master_coa(*)"
        ).eq("deal_id", deal_id)
        
        if min_confidence is not None:
            query = query.gte("confidence", min_confidence)
        if max_confidence is not None:
            query = query.lte("confidence", max_confidence)
        
        query = query.range(offset, offset + limit - 1)
        result = query.execute()
        return result.data
    
    async def bulk_insert_transactions(self, transactions: list[dict]) -> list[dict]:
        result = self.client.table("gl_transactions").insert(transactions).execute()
        return result.data
    
    async def update_transaction_mapping(
        self, 
        transaction_id: str, 
        mapped_coa_id: str, 
        confidence: float,
        is_verified: bool = False
    ) -> dict:
        result = self.client.table("gl_transactions").update({
            "mapped_coa_id": mapped_coa_id,
            "confidence": confidence,
            "is_verified": is_verified
        }).eq("id", transaction_id).execute()
        return result.data[0] if result.data else None
    
    async def verify_transactions(self, transaction_ids: list[str]) -> list[dict]:
        result = self.client.table("gl_transactions").update({
            "is_verified": True
        }).in_("id", transaction_ids).execute()
        return result.data
    
    # Master COA
    async def get_all_coa(self) -> list[dict]:
        result = self.client.table("master_coa").select("*").eq("is_active", True).execute()
        return result.data
    
    async def get_coa_by_category(self, category: str) -> list[dict]:
        result = self.client.table("master_coa").select("*").eq("category", category).execute()
        return result.data
    
    # Open Items
    async def get_open_items_for_deal(self, deal_id: str) -> list[dict]:
        result = self.client.table("open_items").select(
            "*, gl_transactions(*)"
        ).eq("deal_id", deal_id).execute()
        return result.data
    
    async def create_open_item(self, open_item: dict) -> dict:
        result = self.client.table("open_items").insert(open_item).execute()
        return result.data[0] if result.data else None
    
    async def update_open_item_status(self, item_id: str, status: str) -> dict:
        result = self.client.table("open_items").update({
            "status": status
        }).eq("id", item_id).execute()
        return result.data[0] if result.data else None
    
    # Upload Jobs
    async def create_upload_job(self, job_data: dict) -> dict:
        result = self.client.table("upload_jobs").insert(job_data).execute()
        return result.data[0] if result.data else None
    
    async def update_upload_job(self, job_id: str, updates: dict) -> dict:
        result = self.client.table("upload_jobs").update(updates).eq("id", job_id).execute()
        return result.data[0] if result.data else None
    
    async def get_upload_job(self, job_id: str) -> dict:
        result = self.client.table("upload_jobs").select("*").eq("id", job_id).single().execute()
        return result.data
    
    # Vector Search
    async def vector_search_transactions(
        self, 
        embedding: list[float], 
        limit: int = 5,
        verified_only: bool = True
    ) -> list[dict]:
        """
        Perform cosine similarity search on verified transactions.
        Returns transactions with similarity scores.
        """
        # Using Supabase's RPC for vector search
        params = {
            "query_embedding": embedding,
            "match_count": limit,
            "filter_verified": verified_only
        }
        
        result = self.client.rpc("match_transactions", params).execute()
        return result.data
