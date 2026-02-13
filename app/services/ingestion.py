"""
AceCPAs Backend - Ingestion Service
Excel file processing with heuristic header detection and validation.
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd

from app.config import get_settings


class TrialBalanceError(Exception):
    """Raised when GL transactions don't balance to zero."""
    
    def __init__(self, imbalance: Decimal, message: str = None):
        self.imbalance = imbalance
        self.message = message or f"Trial balance error: imbalance of {imbalance}"
        super().__init__(self.message)


class HeaderDetectionError(Exception):
    """Raised when header row cannot be detected."""
    pass


class IngestionService:
    """
    Service for processing GL Excel files.
    Handles header detection, normalization, validation, and preparation for DB insert.
    """
    
    # Keywords to detect header row
    HEADER_KEYWORDS = [
        'date', 'account', 'amount', 'description', 'desc',
        'debit', 'credit', 'vendor', 'payee', 'memo', 'reference',
        'transaction', 'balance', 'category', 'type', 'name'
    ]
    
    # Minimum keywords required to identify header row
    MIN_HEADER_KEYWORDS = 3
    
    # Maximum rows to scan for header
    MAX_HEADER_SCAN_ROWS = 50
    
    # Column mapping patterns (regex)
    COLUMN_PATTERNS = {
        'date': r'(?i)(date|trans.*date|posting.*date|effective)',
        'account': r'(?i)(account|acct|gl.*account|account.*name|account.*number)',
        'description': r'(?i)(desc|description|memo|narrative|particulars|details)',
        'amount': r'(?i)(amount|value|total|sum)',
        'debit': r'(?i)(debit|dr)',
        'credit': r'(?i)(credit|cr)',
        'vendor': r'(?i)(vendor|payee|supplier|merchant|name)',
        'reference': r'(?i)(ref|reference|check.*no|cheque|doc)',
    }
    
    def __init__(self):
        self.settings = get_settings()
    
    def detect_header_row(self, df: pd.DataFrame) -> int:
        """
        Heuristically detect the header row in an Excel file.
        Scans first N rows looking for a row with at least MIN_HEADER_KEYWORDS matches.
        
        Returns:
            Row index of header row (0-indexed)
            
        Raises:
            HeaderDetectionError: If no suitable header row found
        """
        max_rows = min(self.MAX_HEADER_SCAN_ROWS, len(df))
        
        best_row = -1
        best_score = 0
        
        for row_idx in range(max_rows):
            # Safely convert all values to string (handles floats, NaNs, etc.)
            row_values = [str(val).lower() for val in df.iloc[row_idx].values]
            row_text = ' '.join(row_values)
            
            # Count keyword matches
            score = sum(1 for keyword in self.HEADER_KEYWORDS if keyword in row_text)
            
            if score > best_score:
                best_score = score
                best_row = row_idx
        
        if best_score < self.MIN_HEADER_KEYWORDS:
            raise HeaderDetectionError(
                f"Could not detect header row. Best match had only {best_score} keywords. "
                f"Expected at least {self.MIN_HEADER_KEYWORDS} of: {', '.join(self.HEADER_KEYWORDS)}"
            )
        
        return best_row
    
    def normalize_columns(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """
        Normalize column names to standard keys.
        
        Returns:
            Tuple of (normalized DataFrame, column mapping dict)
        """
        column_mapping = {}
        
        for col in df.columns:
            col_lower = str(col).lower().strip()
            
            for standard_name, pattern in self.COLUMN_PATTERNS.items():
                if re.search(pattern, col_lower):
                    if standard_name not in column_mapping:
                        column_mapping[standard_name] = col
                    break
        
        # Rename columns to standard names
        reverse_mapping = {v: k for k, v in column_mapping.items()}
        df = df.rename(columns=reverse_mapping)
        
        return df, column_mapping
    
    def parse_date(self, value: Any) -> Optional[datetime]:
        """Parse various date formats to datetime."""
        if pd.isna(value):
            return None
        
        if isinstance(value, datetime):
            return value
        
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        
        # Try common date formats
        date_formats = [
            '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y',
            '%m-%d-%Y', '%d-%m-%Y',
            '%Y/%m/%d', '%m/%d/%y', '%d/%m/%y',
            '%b %d, %Y', '%B %d, %Y',
            '%d %b %Y', '%d %B %Y',
        ]
        
        str_value = str(value).strip()
        
        for fmt in date_formats:
            try:
                return datetime.strptime(str_value, fmt)
            except ValueError:
                continue
        
        # Try pandas parser as fallback
        try:
            return pd.to_datetime(value).to_pydatetime()
        except Exception:
            return None
    
    def parse_amount(self, value: Any) -> Optional[Decimal]:
        """Parse currency values to Decimal, handling various formats."""
        if pd.isna(value):
            return None
        
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        
        str_value = str(value).strip()
        
        # Handle empty strings
        if not str_value or str_value == '-':
            return Decimal('0')
        
        # Check for parentheses (negative numbers in accounting)
        is_negative = '(' in str_value and ')' in str_value
        
        # Remove currency symbols and formatting
        cleaned = re.sub(r'[^\d.\-,]', '', str_value)
        
        # Handle European format (comma as decimal separator)
        if ',' in cleaned and '.' in cleaned:
            # Assume last separator is decimal
            if cleaned.rfind(',') > cleaned.rfind('.'):
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        elif ',' in cleaned and '.' not in cleaned:
            # Could be thousands separator or decimal
            # If only one comma and 1-2 digits after, treat as decimal
            parts = cleaned.split(',')
            if len(parts) == 2 and len(parts[1]) <= 2:
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        
        try:
            amount = Decimal(cleaned or '0')
            return -amount if is_negative else amount
        except InvalidOperation:
            return None
    
    def process_dataframe(
        self,
        df: pd.DataFrame,
        deal_id: str,
        organization_id: str,
        source_file: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Process a DataFrame of GL transactions.
        
        Args:
            df: Raw DataFrame from Excel
            deal_id: UUID of the deal
            source_file: Original filename
            
        Returns:
            Tuple of (list of transaction dicts, processing stats)
            
        Raises:
            TrialBalanceError: If transactions don't balance
        """
        stats = {
            'rows_read': len(df),
            'rows_processed': 0,
            'rows_skipped': 0,
            'parse_errors': [],
            'total_debits': Decimal('0'),
            'total_credits': Decimal('0'),
        }
        
        transactions = []
        
        for idx, row in df.iterrows():
            try:
                # Parse date
                raw_date = None
                if 'date' in df.columns:
                    raw_date = self.parse_date(row.get('date'))
                
                # Parse amount - handle debit/credit columns
                amount = None
                if 'amount' in df.columns:
                    amount = self.parse_amount(row.get('amount'))
                elif 'debit' in df.columns or 'credit' in df.columns:
                    debit = self.parse_amount(row.get('debit')) or Decimal('0')
                    credit = self.parse_amount(row.get('credit')) or Decimal('0')
                    amount = debit - credit
                
                if amount is None:
                    stats['rows_skipped'] += 1
                    stats['parse_errors'].append(f"Row {idx}: Could not parse amount")
                    continue
                
                # Track debits/credits for validation
                if amount > 0:
                    stats['total_debits'] += amount
                else:
                    stats['total_credits'] += abs(amount)
                
                # Build transaction dict - MATCHING POSTGRES SCHEMA
                # gl_transactions schema: transaction_date, account_name, description, vendor_name, amount, row_number
                transaction = {
                    'deal_id': deal_id,
                    'organization_id': organization_id,
                    'transaction_date': raw_date.strftime('%Y-%m-%d') if raw_date else None,
                    'account_name': str(row.get('account', ''))[:500] if pd.notna(row.get('account')) else None,
                    'description': str(row.get('description', ''))[:1000] if pd.notna(row.get('description')) else None,
                    'vendor_name': str(row.get('vendor', ''))[:255] if pd.notna(row.get('vendor')) else None,
                    'amount': str(amount),  # Convert to string for JSON serialization
                    'original_data': {'source_file': source_file, 'raw_account': str(row.get('account', ''))},
                    'row_number': int(idx) + 1,  # 1-indexed for user display
                }
                
                transactions.append(transaction)
                stats['rows_processed'] += 1
                
            except Exception as e:
                stats['rows_skipped'] += 1
                stats['parse_errors'].append(f"Row {idx}: {str(e)}")
        
        return transactions, stats
    
    def validate_trial_balance(
        self,
        transactions: List[Dict[str, Any]],
        tolerance: Decimal = Decimal('0.01')
    ) -> Tuple[bool, Decimal]:
        """
        Validate that transactions balance to zero.
        
        Args:
            transactions: List of transaction dicts with 'amount' key
            tolerance: Acceptable imbalance threshold
            
        Returns:
            Tuple of (is_balanced, total_imbalance)
            
        Raises:
            TrialBalanceError: If imbalance exceeds tolerance
        """
        total = sum(Decimal(t['amount']) for t in transactions)
        
        is_balanced = abs(total) <= tolerance
        
        if not is_balanced:
            raise TrialBalanceError(
                imbalance=total,
                message=f"Trial balance failed: net imbalance of ${total:,.2f}. "
                        f"Transactions must sum to zero (within ${tolerance} tolerance)."
            )
        
        return True, total
    
    def process_excel_file(
        self,
        file_content: bytes,
        deal_id: str,
        organization_id: str,
        filename: str,
        validate: bool = True
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Main entry point: Process an Excel file from bytes.
        
        Args:
            file_content: Raw bytes of Excel file
            deal_id: UUID of the deal
            organization_id: UUID of the organization
            filename: Original filename
            
        Returns:
            Tuple of (transactions list, processing stats)
        """
        # Read Excel file
        if filename.endswith('.xlsx'):
            df = pd.read_excel(BytesIO(file_content), engine='openpyxl', header=None)
        elif filename.endswith('.xls'):
            df = pd.read_excel(BytesIO(file_content), engine='xlrd', header=None)
        else:
            raise ValueError(f"Unsupported file format: {filename}")
        
        # Detect header row
        header_row = self.detect_header_row(df)
        
        # Re-read with correct header
        if filename.endswith('.xlsx'):
            df = pd.read_excel(
                BytesIO(file_content),
                engine='openpyxl',
                header=header_row
            )
        else:
            df = pd.read_excel(
                BytesIO(file_content),
                engine='xlrd',
                header=header_row
            )
        
        # Normalize column names
        df, column_mapping = self.normalize_columns(df)
        
        # Process rows
        transactions, stats = self.process_dataframe(df, deal_id, organization_id, filename)
        stats['header_row'] = header_row + 1  # 1-indexed for display
        stats['column_mapping'] = column_mapping
        
        # Validate trial balance
        if validate:
            self.validate_trial_balance(transactions)
        
        return transactions, stats
