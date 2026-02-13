from decimal import Decimal
from typing import List, Dict, Any
from uuid import UUID
import pandas as pd
from fastapi import APIRouter, HTTPException

from app.database import get_supabase_admin_client
from app.models.schemas import (
    ConsolidationRequest,
    ConsolidationResponse,
    ConsolidatedLineItem,
    ConsolidatedValue,
    ConsolidationDealInfo
)

router = APIRouter()

@router.post(
    "/pl",
    response_model=ConsolidationResponse,
    summary="Get Consolidated P&L",
    description="Aggregate P&L across multiple deals based on Chart of Accounts mapping."
)
async def get_consolidated_pl(request: ConsolidationRequest):
    """
    Generate a consolidated P&L report for selected deals.
    
    Aggregates GL transactions by their mapped COA category/account.
    Returns a matrix of [Account x Deals].
    """
    client = get_supabase_admin_client()
    # Convert UUIDs to strings
    deal_ids_str = [str(d) for d in request.deal_ids]
    
    if not deal_ids_str:
        return ConsolidationResponse(line_items=[], deals=[])

    # 1. Fetch Deal Metadata
    deals_res = client.table("deals").select("*").in_("id", deal_ids_str).execute()
    deals_data = deals_res.data or []
    
    # 2. Fetch Transactions
    # We fetch amount, deal_id, account_name, and the joined master_coa details
    # Note: This could be heavy for very large datasets. 
    # Optimization: Filter by date range if provided in request (TODO)
    tx_res = client.table("gl_transactions").select(
        "amount, deal_id, account_name, master_coa(category, subcategory, account_name)"
    ).in_("deal_id", deal_ids_str).execute()
    
    transactions = tx_res.data or []
    
    if not transactions:
        return ConsolidationResponse(line_items=[], deals=deals_data)

    # 3. Process with Pandas for efficient aggregation
    df = pd.DataFrame(transactions)
    
    # Helper to extract mapped fields safely
    def extract_mapping(row):
        mapping = row.get('master_coa')
        if mapping:
            return pd.Series({
                'category': mapping.get('category', 'Unmapped'),
                'subcategory': mapping.get('subcategory') or 'Other',
                'std_name': mapping.get('account_name', 'Unknown')
            })
        else:
            return pd.Series({
                'category': 'Unmapped',
                'subcategory': 'Uncategorized',
                'std_name': row.get('account_name', 'Unknown')
            })

    # Apply extraction
    mapping_df = df.apply(extract_mapping, axis=1)
    df = pd.concat([df, mapping_df], axis=1)
    
    # Ensure amount is numeric (decimal -> float for sums, then back to decimal if needed)
    # Pandas handles floats better for aggregation. precision might be slight issue but acceptible for display.
    df['amount_float'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    
    # 4. Group and Aggregate
    # Group by unique line item keys AND deal_id
    grouped = df.groupby(['category', 'subcategory', 'std_name', 'deal_id'])['amount_float'].sum().reset_index()
    
    # 5. Build Response Structure
    line_items_map: Dict[tuple, ConsolidatedLineItem] = {}
    
    # Iterate through grouped data to build the matrix
    # We want one LineItem for each (Category, Sub, Name) tuple
    # containing a list of Values per deal
    
    # First, get all unique keys
    unique_keys = grouped[['category', 'subcategory', 'std_name']].drop_duplicates()
    
    line_items = []
    
    for _, key in unique_keys.iterrows():
        cat = key['category']
        sub = key['subcategory']
        name = key['std_name']
        
        # Filter rows for this line item
        # (This is slightly inefficient O(N*M), simpler would be pivoting)
        # Let's pivot instead!
        
        pass 
    
    # Better approach: Pivot the dataframe so Deals are columns
    pivot_df = grouped.pivot(
        index=['category', 'subcategory', 'std_name'],
        columns='deal_id',
        values='amount_float'
    ).fillna(0).reset_index()
    
    # Now iterate the pivoted rows
    final_items = []
    
    for _, row in pivot_df.iterrows():
        cat = row['category']
        sub = row['subcategory']
        name = row['std_name']
        
        deal_values = []
        total_line = Decimal(0)
        
        # Iterate through provided deals to get their values from columns
        for deal_id in deal_ids_str:
            if deal_id in pivot_df.columns:
                val = Decimal(str(row[deal_id])) # Convert back to Decimal
                deal_values.append(ConsolidatedValue(deal_id=UUID(deal_id), amount=val))
                total_line += val
            else:
                deal_values.append(ConsolidatedValue(deal_id=UUID(deal_id), amount=Decimal(0)))
        
        final_items.append(ConsolidatedLineItem(
            category=cat,
            subcategory=sub,
            account_name=name,
            deal_values=deal_values,
            total_amount=total_line
        ))
        
    return ConsolidationResponse(line_items=final_items, deals=deals_data)
