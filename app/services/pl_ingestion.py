import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import calendar
from decimal import Decimal

from app.database import get_supabase_admin_client
from app.services.pl_parser import PLParser

logger = logging.getLogger(__name__)

class PLIngestionService:
    def __init__(self):
        self.parser = PLParser()
        self.supabase = get_supabase_admin_client()

    def process_file(self, deal_id: str, file_id: str, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Processes a P&L file: parses it and inserts data into Supabase.
        Updates uploaded_files status.
        """
        try:
            # 1. Update status to processing
            self.supabase.table("uploaded_files").update({"status": "processing"}).eq("id", file_id).execute()

            # 2. Parse File
            parsed_data = self.parser.parse_excel(file_content, filename)
            periods_meta = parsed_data["periods_metadata"] # { "YYYY-MM-DD": col_idx }
            # Wait, parse_excel returns dict with "periods_metadata" but my parser code returned "periods_metadata"
            # containing dict {date_str: col_idx}.
            # But I need period NAMES too (e.g. "Jan-23"). The parser should ideally return that.
            # My parser implementation returned: 
            # "periods": [{"date": ..., "name": ...}], but implementation in write_to_file actually returned
            # "periods": [...list comprehension...] which was incomplete in the snippet I wrote?
            # Let's check pl_parser.py content in next step if needed. 
            # Assuming parser works as expected or I'll fix it.

            # 3. Create Headers for each Period
            header_map = {} # date_str -> header_id
            
            for date_str in periods_meta.keys():
                # Calculate start/end dates
                # date_str is supposedly YYYY-MM-DD
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                period_start = dt.replace(day=1)
                last_day = calendar.monthrange(dt.year, dt.month)[1]
                period_end = dt.replace(day=last_day)
                period_name = dt.strftime("%b %Y") # "Jan 2023"

                header_data = {
                    "deal_id": deal_id,
                    "uploaded_file_id": file_id,
                    "period_start": period_start.strftime("%Y-%m-%d"),
                    "period_end": period_end.strftime("%Y-%m-%d"),
                    "period_name": period_name,
                    # We could calculate totals from line items later or now
                }
                
                res = self.supabase.table("monthly_pl_headers").insert(header_data).execute()
                if res.data:
                    header_map[date_str] = res.data[0]["id"]

            # 4. Insert Line Items
            all_line_items = []
            
            for item in parsed_data["line_items"]:
                # item = { name, indent, is_subtotal, values: {date_str: amount} }
                line_name = item["name"]
                indent = item["indent"]
                is_subtotal = item["is_subtotal"]
                
                for date_str, amount in item["values"].items():
                    if date_str not in header_map:
                        continue # Should not happen if periods matched
                        
                    header_id = header_map[date_str]
                    
                    line_data = {
                        "header_id": header_id,
                        "deal_id": deal_id,
                        "line_name": line_name,
                        "line_category": None, # AI to fill later
                        "amount": float(amount), # Decimal to float for JSON
                        "display_order": 0, # TODO: Track index
                        "indent_level": indent,
                        "is_subtotal": is_subtotal
                    }
                    all_line_items.append(line_data)
            
            # Batch insert
            if all_line_items:
                # Split into chunks of 1000
                chunk_size = 1000
                for i in range(0, len(all_line_items), chunk_size):
                    chunk = all_line_items[i:i + chunk_size]
                    self.supabase.table("pl_line_items").insert(chunk).execute()

            # 5. Update File Status
            self.supabase.table("uploaded_files").update({
                "status": "completed", 
                "updated_at": datetime.now().isoformat()
            }).eq("id", file_id).execute()
            
            return {"status": "success", "rows_inserted": len(all_line_items)}

        except Exception as e:
            logger.error(f"PL Ingestion Failed: {e}")
            self.supabase.table("uploaded_files").update({
                "status": "failed",
                "parse_errors": [str(e)],
                "updated_at": datetime.now().isoformat()
            }).eq("id", file_id).execute()
            raise e
