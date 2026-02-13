
import asyncio
import os
import sys
import json

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_supabase_admin_client

async def inspect():
    client = get_supabase_admin_client()
    
    tables = ["gl_transactions", "deals", "organizations", "master_coa", "client_accounts"]
    
    print("--- Database Schema Inspection ---")
    
    for table in tables:
        print(f"\nChecking table: {table}")
        try:
            # Fetch 1 row to see underlying columns
            response = client.table(table).select("*").limit(1).execute()
            if response.data:
                print(f"Columns found in '{table}':")
                print(list(response.data[0].keys()))
            else:
                print(f"Table '{table}' is empty, but accessible.")
                # If empty, we can't easily guess columns via API without inserting.
                # But if it didn't error, the table exists.
        except Exception as e:
            print(f"Error accessing '{table}': {e}")

if __name__ == "__main__":
    asyncio.run(inspect())
