"""
AceCPAs Backend - P&L Parser
Parses Monthly P&L Excel files into normalized database structure.
"""
import pandas as pd
import numpy as np
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional
from io import BytesIO
import re

class PLParsingError(Exception):
    """Raised when P&L parsing fails."""
    pass

class PLParser:
    """
    Parses Monthly P&L Excel files.
    Identifies period columns (Jan-23, Feb-23...) and line items.
    """

    def __init__(self):
        pass

    def parse_excel(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Main entry point.
        Returns a dictionary containing:
        - periods: List of {date: datetime, name: str}
        - line_items: List of {name: str, values: {date: amount}, indent: int, is_subtotal: bool}
        """
        try:
            if filename.endswith('.xlsx'):
                df = pd.read_excel(BytesIO(file_content), engine='openpyxl', header=None)
            elif filename.endswith('.xls'):
                df = pd.read_excel(BytesIO(file_content), engine='xlrd', header=None)
            elif filename.endswith('.csv'):
                 df = pd.read_csv(BytesIO(file_content), header=None)
            else:
                raise PLParsingError(f"Unsupported file format: {filename}")
        except Exception as e:
            raise PLParsingError(f"Failed to open file: {str(e)}")

        # 1. Detect Header Row (containing dates)
        header_row_idx, period_cols = self._detect_header_and_periods(df)
        
        if header_row_idx is None:
             raise PLParsingError("Could not detect header row with valid dates (e.g., Jan-23, 2023-01-31).")
             
        # 2. Identify Description Column
        desc_col_idx = self._identify_description_column(df, header_row_idx, period_cols)
        
        # 3. Extract Data
        # Re-read with header to get clean dataframe, or just slice
        # Slicing is safer to preserve original indexing
        line_items = []
        
        # Iterate rows starting after header
        for idx in range(header_row_idx + 1, len(df)):
            row = df.iloc[idx]
            
            # Get Line Name
            raw_name = row[desc_col_idx]
            if pd.isna(raw_name) or str(raw_name).strip() == "":
                continue
                
            line_name = str(raw_name).strip()
            
            # Heuristics for formatting
            indent = self._estimate_indent(str(raw_name))
            is_subtotal = self._is_subtotal(line_name)
            
            # Extract amounts for each period
            values = {}
            has_data = False
            
            for date_str, col_idx in period_cols.items():
                val = row[col_idx]
                amount = self._parse_amount(val)
                if amount is not None:
                     values[date_str] = amount
                     if amount != 0:
                         has_data = True
            
            if has_data or is_subtotal: # Keep subtotals even if 0?
                line_items.append({
                    "name": line_name,
                    "indent": indent,
                    "is_subtotal": is_subtotal,
                    "values": values # Key is date string ISO
                })
                
        return {
            "periods": [{"date": p["date"], "name": p["name"], "original_col": col} for p, col in zip(period_cols.values(), period_cols.keys())], # slightly simplified structure logic needed
             # Fix structure: period_cols is { "ISO-DATE": col_index }
             # We want a list of periods found.
            "periods_metadata": period_cols, 
            "line_items": line_items
        }

    def _detect_header_and_periods(self, df: pd.DataFrame) -> Tuple[Optional[int], Dict[str, int]]:
        """
        Scans first 20 rows to find a row with multiple Date-like columns.
        Returns (row_index, { "YYYY-MM-DD": col_index })
        """
        best_row = None
        best_period_count = 0
        best_periods = {}
        
        max_scan = min(20, len(df))
        
        for r_idx in range(max_scan):
            row = df.iloc[r_idx]
            periods = {} # "YYYY-MM-DD" -> col_idx
            
            for c_idx, val in enumerate(row):
                if pd.isna(val): continue
                
                # Check if it's a date
                dt = self._parse_date(val)
                if dt:
                    iso_date = dt.strftime("%Y-%m-%d")
                    periods[iso_date] = c_idx
            
            # Heuristic: A P&L usually has at least 3 months, or 1 month + Total? 
            # Let's say at least 1 valid date found.
            if len(periods) > best_period_count:
                best_period_count = len(periods)
                best_row = r_idx
                best_periods = periods
        
        if best_period_count >= 1: # Allow even single month P&L
            return best_row, best_periods
            
        return None, {}

    def _identify_description_column(self, df: pd.DataFrame, header_idx: int, period_cols: Dict[str, int]) -> int:
        """
        Finds the column that likely contains line item names.
        It should NOT be one of the period columns.
        It usually is the first column, or the one with most string values below header.
        """
        all_cols = set(range(len(df.columns)))
        period_col_indices = set(period_cols.values())
        candidate_cols = list(all_cols - period_col_indices)
        
        if not candidate_cols:
            raise PLParsingError("Cannot identify description column (all columns identify as dates?)")
            
        # Simple heuristic: First non-date column is usually description
        candidate_cols.sort()
        return candidate_cols[0]

    def _parse_date(self, val: Any) -> Optional[datetime]:
        if isinstance(val, datetime): return val
        if isinstance(val, pd.Timestamp): return val.to_pydatetime()
        
        s = str(val).strip()
        # Common formats: "Jan-23", "Jan 2023", "1/31/2023"
        formats = [
            "%b-%y", "%B-%y", "%b %Y", "%B %Y", 
            "%m/%d/%Y", "%Y-%m-%d", "%d-%b-%y"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt)
            except:
                continue
        return None

    def _parse_amount(self, val: Any) -> Optional[Decimal]:
        if pd.isna(val): return None
        if isinstance(val, (int, float)): return Decimal(str(val))
        s = str(val).strip().replace(',', '').replace('$', '').replace(')', '')
        if '(' in str(val): s = '-' + s # Handle accounting negative
        try:
            return Decimal(s)
        except:
            return None

    def _estimate_indent(self, raw_str: str) -> int:
        # Count leading spaces? Excel often trims. 
        # But if read via openpyxl, maybe we can get style indent? 
        # For now, just regex valid leading spaces if they exist
        match = re.search(r'^(\s*)', raw_str)
        return len(match.group(1)) if match else 0

    def _is_subtotal(self, name: str) -> bool:
        name = name.lower()
        return 'total' in name or 'gross profit' in name or 'net income' in name or 'ebitda' in name
