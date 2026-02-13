"""
AceCPAs Backend - EBITDA Bridge Router
Computes the Revenue → Gross Profit → EBITDA waterfall from GL transactions.
"""
from decimal import Decimal
from uuid import UUID
import pandas as pd
from fastapi import APIRouter, HTTPException

from app.database import get_supabase_admin_client
from app.models.schemas import (
    EBITDABridgeRequest,
    EBITDABridgeResponse,
    BridgeStep,
)

router = APIRouter()

# Map COA categories to P&L buckets for the waterfall
REVENUE_CATEGORIES = {"Revenue", "Income", "Sales"}
COGS_CATEGORIES = {"Cost of Goods Sold", "COGS", "Cost of Revenue", "Cost of Sales"}
OPEX_CATEGORIES = {"Operating Expenses", "OpEx", "SG&A", "Selling, General & Administrative",
                    "General & Administrative", "Sales & Marketing", "Research & Development"}
DA_KEYWORDS = {"depreciation", "amortization", "d&a", "dep & amort"}
INTEREST_KEYWORDS = {"interest expense", "interest income", "interest"}
TAX_KEYWORDS = {"income tax", "tax expense", "provision for taxes", "tax"}
OTHER_INCOME_CATEGORIES = {"Other Income", "Other Expense", "Non-Operating"}


@router.post(
    "/bridge",
    response_model=EBITDABridgeResponse,
    summary="Get EBITDA Bridge",
    description="Compute the Revenue → Gross Profit → EBITDA waterfall for a deal."
)
async def get_ebitda_bridge(request: EBITDABridgeRequest):
    """
    Build an EBITDA Bridge (waterfall) for a single deal.
    
    Steps:
    1. Revenue (total)
    2. - COGS → Gross Profit
    3. - Operating Expenses → Operating Income
    4. + D&A add-back → EBITDA
    5. - D&A, - Interest, - Taxes → Net Income
    """
    client = get_supabase_admin_client()
    deal_id_str = str(request.deal_id)

    # Fetch deal info
    deal_res = client.table("deals").select("id, client_name").eq("id", deal_id_str).single().execute()
    if not deal_res.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    deal = deal_res.data

    # Fetch all GL transactions with COA mapping
    tx_res = client.table("gl_transactions").select(
        "amount, account_name, master_coa(category, subcategory, account_name)"
    ).eq("deal_id", deal_id_str).execute()

    transactions = tx_res.data or []
    if not transactions:
        raise HTTPException(status_code=404, detail="No transactions found for this deal")

    # Process with Pandas
    df = pd.DataFrame(transactions)
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)

    # Extract category from master_coa join
    def get_category(row):
        m = row.get('master_coa')
        return m.get('category', 'Uncategorized') if m else 'Uncategorized'

    def get_account_name(row):
        m = row.get('master_coa')
        return (m.get('account_name', '') if m else row.get('account_name', '')).lower()

    df['category'] = df.apply(get_category, axis=1)
    df['acct_lower'] = df.apply(get_account_name, axis=1)

    # Classify into P&L buckets
    def classify(row):
        cat = row['category']
        acct = row['acct_lower']

        if cat in REVENUE_CATEGORIES:
            return 'revenue'
        if cat in COGS_CATEGORIES:
            return 'cogs'
        # Check D&A before general OpEx (D&A is often under OpEx)
        if any(kw in acct for kw in DA_KEYWORDS):
            return 'da'
        if any(kw in acct for kw in INTEREST_KEYWORDS):
            return 'interest'
        if any(kw in acct for kw in TAX_KEYWORDS):
            return 'taxes'
        if cat in OPEX_CATEGORIES:
            return 'opex'
        if cat in OTHER_INCOME_CATEGORIES:
            return 'other'
        return 'opex'  # Default unmapped to opex

    df['bucket'] = df.apply(classify, axis=1)

    # Aggregate
    buckets = df.groupby('bucket')['amount'].sum().to_dict()

    revenue = Decimal(str(round(buckets.get('revenue', 0), 2)))
    cogs = Decimal(str(round(abs(buckets.get('cogs', 0)), 2)))
    opex = Decimal(str(round(abs(buckets.get('opex', 0)), 2)))
    da = Decimal(str(round(abs(buckets.get('da', 0)), 2)))
    interest = Decimal(str(round(abs(buckets.get('interest', 0)), 2)))
    taxes = Decimal(str(round(abs(buckets.get('taxes', 0)), 2)))
    other = Decimal(str(round(buckets.get('other', 0), 2)))

    # Build waterfall
    gross_profit = revenue - cogs
    operating_income = gross_profit - opex + other
    ebitda = operating_income + da
    net_income = operating_income - interest - taxes

    steps = [
        BridgeStep(label="Revenue", value=revenue, running_total=revenue,
                   step_type="total", category="Revenue"),
        BridgeStep(label="COGS", value=-cogs, running_total=gross_profit,
                   step_type="subtraction", category="COGS"),
        BridgeStep(label="Gross Profit", value=gross_profit, running_total=gross_profit,
                   step_type="total", category="Subtotal"),
        BridgeStep(label="Operating Expenses", value=-opex, running_total=gross_profit - opex,
                   step_type="subtraction", category="OpEx"),
        BridgeStep(label="Other Income/Expense", value=other, running_total=operating_income,
                   step_type="addition" if other >= 0 else "subtraction", category="Other"),
        BridgeStep(label="Operating Income", value=operating_income, running_total=operating_income,
                   step_type="total", category="Subtotal"),
        BridgeStep(label="D&A Add-back", value=da, running_total=ebitda,
                   step_type="addition", category="Adjustment"),
        BridgeStep(label="EBITDA", value=ebitda, running_total=ebitda,
                   step_type="total", category="EBITDA"),
    ]

    return EBITDABridgeResponse(
        deal_id=request.deal_id,
        client_name=deal.get('client_name', 'Unknown'),
        steps=steps,
        revenue=revenue,
        gross_profit=gross_profit,
        ebitda=ebitda,
        net_income=net_income,
    )
