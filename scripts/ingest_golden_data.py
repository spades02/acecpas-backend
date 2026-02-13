
import os
import sys
import asyncio
import pandas as pd
import logging
from typing import List, Dict, Any

# Add parent directory to path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.database import get_supabase_admin_client
from langchain_openai import OpenAIEmbeddings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_golden")

BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Golden Data Set - 5 Deals of GLs before and after")

def find_golden_files(base_dir: str) -> List[str]:
    golden_files = []
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if "Final Output" in root and file.endswith(".xlsx") and not file.startswith("~$"):
                golden_files.append(os.path.join(root, file))
    return golden_files

async def process_file(file_path: str, embeddings_model, supabase):
    logger.info(f"Processing file: {file_path}")
    
    try:
        xls = pd.ExcelFile(file_path)
    except Exception as e:
        logger.error(f"Failed to read Excel file {file_path}: {e}")
        return

    # Helper to clean string
    def clean(val):
        s = str(val).strip()
        return "" if s.lower() in ('nan', 'none', 'null', '') else s

    # Sheets to scan which contain row-level GL data
    # Based on inspection, these sheets usually have the data
    valid_sheets = ['sheet1', 'consolidated gl', 'formatted gl', 'formatted gl (2)']
    
    target_sheet = None
    for sheet in xls.sheet_names:
        if sheet.lower().strip() in valid_sheets:
            target_sheet = sheet
            break
            
    if not target_sheet:
        logger.warning(f"No valid data sheet found in {file_path}. Sheets: {xls.sheet_names}. Skipping.")
        return

    logger.info(f"Reading sheet: '{target_sheet}'")
    
    # Read sheet. Header detection:
    # Usually row 1 (index 1) has the headers based on inspection (e.g. ['names', 'formatted name', ...])
    # But sometimes row 0. inspection showed row 1 for Consolidated GL often.
    # Let's read a few rows and heuristic detect header again or just hardcode specific known offsets?
    # AWS Roofing: 'Consolidated GL' -> Row 1 has headers (index 1). Row 0 has random totals.
    # Joes Roofing: 'Formatted GL' -> Row 1 has headers.
    # Mindspire: 'Consolidated GL' -> Row 1 has headers.
    # Sheet1 (Joes): Row 1.
    
    # Safe bet: Read w/ header=1 (skipping row 0)
    try:
        df = pd.read_excel(file_path, sheet_name=target_sheet, header=1)
    except Exception as e:
        logger.error(f"Error reading sheet {target_sheet}: {e}")
        return

    # Lowercase cols for consistent access
    df.columns = [str(c).lower().strip() for c in df.columns]
    
    # Identify Mapping Columns
    # Input:
    # - Account Name: 'formatted name' or 'account name' or 'account'
    # - Description: 'memo/description' or 'memo' or 'description'
    # - Vendor: 'name' (often this is the vendor/payee column in these reports)
    
    # Output (Truth):
    # - Category: 'main' or 'main ' (trailing space seen in inspection)
    # - Sub Category: 'sub1'
    # - Account: 'sub2' or 'sub3' (depending on granularity)
    
    cols = df.columns
    
    acc_col = next((c for c in cols if c in ['formatted name', 'account name', 'account']), None)
    desc_col = next((c for c in cols if 'memo' in c or 'description' in c), None)
    vendor_col = next((c for c in cols if c == 'name'), None)
    
    cat_col = next((c for c in cols if 'main' in c), None) # 'main' or 'main '
    sub2_col = next((c for c in cols if c == 'sub2'), None) # Specific Account
    sub1_col = next((c for c in cols if c == 'sub1'), None)
    
    if not (acc_col and cat_col):
        logger.warning(f"Could not identify required columns in {target_sheet}. Found: {cols}. Skipping.")
        return

    logger.info(f"Columns: Account='{acc_col}', Vendor='{vendor_col}', Cat='{cat_col}', Target='{sub2_col}'")

    records_to_insert = []
    
    for _, row in df.iterrows():
        # Extracted Input
        acc_val = clean(row.get(acc_col))
        desc_val = clean(row.get(desc_col))
        vendor_val = clean(row.get(vendor_col))
        
        # Ground Truth
        # Prefer sub2 (account) -> sub1 -> main
        truth_account = clean(row.get(sub2_col)) or clean(row.get(sub1_col))
        truth_category = clean(row.get(cat_col))
        
        # Skip if no useful info
        if not acc_val and not desc_val and not vendor_val:
            continue
        if not truth_category: # Needs at least a category mapping
            continue
            
        # Construct Embedding Text
        text_to_embed = f"{acc_val} {desc_val} {vendor_val}".strip()
        
        records_to_insert.append({
            "account_name": acc_val,
            "description": desc_val,
            "vendor_name": vendor_val,
            "correct_coa_name": truth_account, # The name of the Master Account it mapped to
            "correct_category": truth_category,
            "source_deal": os.path.basename(os.path.dirname(os.path.dirname(file_path))),
            "text_to_embed": text_to_embed
        })
    
    if not records_to_insert:
        logger.info("No valid records found to insert.")
        return

    # De-duplicate to save tokens/time (many recurring transactions)
    # Use text_to_embed + correct_coa as unique key
    unique_records = {}
    for r in records_to_insert:
        key = f"{r['text_to_embed']}||{r['correct_coa_name']}"
        unique_records[key] = r
        
    final_records = list(unique_records.values())
    logger.info(f"Processing {len(final_records)} unique records (from {len(records_to_insert)} total rows)...")

    # Batch process embeddings
    batch_size = 50
    for i in range(0, len(final_records), batch_size):
        batch = final_records[i:i+batch_size]
        texts = [b["text_to_embed"] for b in batch]
        
        try:
            embeddings_list = embeddings_model.embed_documents(texts)
            
            # Prepare rows for DB
            db_rows = []
            for j, item in enumerate(batch):
                row = item.copy()
                del row["text_to_embed"]
                row["embedding"] = embeddings_list[j]
                db_rows.append(row)
                
            # Upsert
            supabase.table("golden_mappings").insert(db_rows).execute()
            logger.info(f"Inserted batch {i//batch_size + 1}")
            
        except Exception as e:
            logger.error(f"Error batch processing: {e}")

async def main():
    settings = get_settings()
    supabase = get_supabase_admin_client()
    
    embeddings = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        openai_api_key=settings.openai_api_key
    )
    
    files = find_golden_files(BASE_DIR)
    logger.info(f"Found {len(files)} golden data files.")
    
    for f in files:
        await process_file(f, embeddings, supabase)

if __name__ == "__main__":
    asyncio.run(main())
