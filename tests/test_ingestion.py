"""
Tests for the Ingestion Service
"""
import pytest
from decimal import Decimal
from datetime import datetime
from io import BytesIO

import pandas as pd

from app.services.ingestion import (
    IngestionService,
    TrialBalanceError,
    HeaderDetectionError
)


class TestIngestionService:
    """Test suite for IngestionService."""
    
    @pytest.fixture
    def service(self):
        return IngestionService()
    
    @pytest.fixture
    def sample_gl_data(self):
        """Create a sample GL DataFrame that balances."""
        return pd.DataFrame({
            'Date': ['2024-01-01', '2024-01-02', '2024-01-03'],
            'Account': ['Cash', 'Revenue', 'Expenses'],
            'Description': ['Opening balance', 'Sale #1', 'Office supplies'],
            'Amount': [1000.00, -500.00, -500.00]  # Sums to 0
        })
    
    @pytest.fixture
    def unbalanced_gl_data(self):
        """Create an unbalanced GL DataFrame."""
        return pd.DataFrame({
            'Date': ['2024-01-01', '2024-01-02'],
            'Account': ['Cash', 'Revenue'],
            'Description': ['Opening balance', 'Sale #1'],
            'Amount': [1000.00, -500.00]  # Sums to 500 - not balanced!
        })
    
    def test_detect_header_row_simple(self, service):
        """Test header detection with standard headers."""
        df = pd.DataFrame([
            ['Report Title', '', '', ''],
            ['Generated: 2024', '', '', ''],
            ['Date', 'Account', 'Description', 'Amount'],  # Header row
            ['2024-01-01', 'Cash', 'Opening', '1000.00']
        ])
        
        header_row = service.detect_header_row(df)
        assert header_row == 2  # Index 2 (0-indexed)
    
    def test_detect_header_row_different_labels(self, service):
        """Test header detection with alternative labels."""
        df = pd.DataFrame([
            ['Trans Date', 'GL Account', 'Memo', 'Debit', 'Credit'],
            ['2024-01-01', '1000', 'Opening', '1000.00', '']
        ])
        
        header_row = service.detect_header_row(df)
        assert header_row == 0
    
    def test_detect_header_row_failure(self, service):
        """Test that header detection fails with no valid headers."""
        df = pd.DataFrame([
            ['abc', 'def', 'ghi'],
            ['123', '456', '789']
        ])
        
        with pytest.raises(HeaderDetectionError):
            service.detect_header_row(df)
    
    def test_parse_date_various_formats(self, service):
        """Test parsing various date formats."""
        test_cases = [
            ('2024-01-15', datetime(2024, 1, 15)),
            ('01/15/2024', datetime(2024, 1, 15)),
            ('15/01/2024', datetime(2024, 1, 15)),
            ('Jan 15, 2024', datetime(2024, 1, 15)),
        ]
        
        for date_str, expected in test_cases:
            result = service.parse_date(date_str)
            assert result is not None
            assert result.year == expected.year
            assert result.month == expected.month
            assert result.day == expected.day
    
    def test_parse_amount_various_formats(self, service):
        """Test parsing various amount formats."""
        test_cases = [
            ('1000.00', Decimal('1000.00')),
            ('$1,000.00', Decimal('1000.00')),
            ('(500.00)', Decimal('-500.00')),  # Accounting negative
            ('1.234,56', Decimal('1234.56')),  # European format
            ('-500', Decimal('-500')),
        ]
        
        for amount_str, expected in test_cases:
            result = service.parse_amount(amount_str)
            assert result == expected, f"Failed for {amount_str}: got {result}"
    
    def test_validate_trial_balance_pass(self, service, sample_gl_data):
        """Test trial balance validation passes for balanced transactions."""
        transactions = [
            {'amount': '1000.00'},
            {'amount': '-500.00'},
            {'amount': '-500.00'}
        ]
        
        is_balanced, total = service.validate_trial_balance(transactions)
        assert is_balanced is True
        assert total == Decimal('0')
    
    def test_validate_trial_balance_fail(self, service):
        """Test trial balance validation fails for unbalanced transactions."""
        transactions = [
            {'amount': '1000.00'},
            {'amount': '-500.00'}
        ]
        
        with pytest.raises(TrialBalanceError) as exc_info:
            service.validate_trial_balance(transactions)
        
        assert exc_info.value.imbalance == Decimal('500')
    
    def test_normalize_columns(self, service):
        """Test column normalization."""
        df = pd.DataFrame({
            'Transaction Date': [],
            'GL Account Code': [],
            'Transaction Description': [],
            'Amount USD': []
        })
        
        normalized_df, mapping = service.normalize_columns(df)
        
        assert 'date' in normalized_df.columns
        assert 'account' in normalized_df.columns
        assert 'description' in normalized_df.columns
        assert 'amount' in normalized_df.columns
    
    def test_process_dataframe(self, service, sample_gl_data):
        """Test full dataframe processing."""
        # Rename to expected column names
        df = sample_gl_data.rename(columns={
            'Date': 'date',
            'Account': 'account',
            'Description': 'description',
            'Amount': 'amount'
        })
        
        transactions, stats = service.process_dataframe(
            df,
            deal_id='test-deal-id',
            source_file='test.xlsx'
        )
        
        assert len(transactions) == 3
        assert stats['rows_processed'] == 3
        assert stats['rows_skipped'] == 0
        
        # Check first transaction
        assert transactions[0]['deal_id'] == 'test-deal-id'
        assert transactions[0]['source_file'] == 'test.xlsx'


class TestIngestionEdgeCases:
    """Edge case tests for ingestion."""
    
    @pytest.fixture
    def service(self):
        return IngestionService()
    
    def test_empty_dataframe(self, service):
        """Test handling of empty dataframe."""
        df = pd.DataFrame({
            'date': [],
            'account': [],
            'description': [],
            'amount': []
        })
        
        transactions, stats = service.process_dataframe(df, 'deal-id', 'test.xlsx')
        
        assert len(transactions) == 0
        assert stats['rows_processed'] == 0
    
    def test_missing_amount_column(self, service):
        """Test handling when amount column is missing."""
        df = pd.DataFrame({
            'date': ['2024-01-01'],
            'account': ['Cash'],
            'description': ['Test']
            # No amount column
        })
        
        transactions, stats = service.process_dataframe(df, 'deal-id', 'test.xlsx')
        
        assert len(transactions) == 0
        assert stats['rows_skipped'] == 1
    
    def test_debit_credit_columns(self, service):
        """Test handling separate debit/credit columns."""
        df = pd.DataFrame({
            'date': ['2024-01-01', '2024-01-02'],
            'account': ['Cash', 'Revenue'],
            'description': ['Deposit', 'Sale'],
            'debit': [1000.00, 0],
            'credit': [0, 1000.00]
        })
        
        transactions, stats = service.process_dataframe(df, 'deal-id', 'test.xlsx')
        
        assert len(transactions) == 2
        assert Decimal(transactions[0]['amount']) == Decimal('1000.00')
        assert Decimal(transactions[1]['amount']) == Decimal('-1000.00')
