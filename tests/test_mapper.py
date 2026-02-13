"""
Tests for the Mapper Agent
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from app.services.mapper_agent import MapperAgentService, TransactionState


class TestMapperAgent:
    """Test suite for MapperAgentService."""
    
    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing."""
        with patch('app.services.mapper_agent.get_settings') as mock:
            settings = Mock()
            settings.openai_api_key = 'test-key'
            settings.openai_embedding_model = 'text-embedding-3-small'
            settings.openai_chat_model = 'gpt-4o'
            settings.mapper_auto_threshold = 0.92
            settings.mapper_min_threshold = 0.5
            mock.return_value = settings
            yield settings
    
    @pytest.fixture
    def mock_supabase(self):
        """Mock Supabase client."""
        with patch('app.services.mapper_agent.get_supabase_admin_client') as mock:
            client = MagicMock()
            mock.return_value = client
            yield client
    
    def test_generate_embedding_text_construction(self, mock_settings, mock_supabase):
        """Test that embedding text is constructed correctly."""
        with patch('app.services.mapper_agent.OpenAIEmbeddings') as mock_embeddings:
            with patch('app.services.mapper_agent.ChatOpenAI'):
                mock_embed_instance = Mock()
                mock_embed_instance.embed_query.return_value = [0.1] * 1536
                mock_embeddings.return_value = mock_embed_instance
                
                service = MapperAgentService()
                
                transaction = {
                    'raw_account': 'Office Supplies',
                    'raw_desc': 'Staples purchase',
                    'vendor': 'Staples Inc'
                }
                
                embedding = service.generate_embedding(transaction)
                
                # Verify embed_query was called with concatenated text
                call_args = mock_embed_instance.embed_query.call_args[0][0]
                assert 'Office Supplies' in call_args
                assert 'Staples purchase' in call_args
                assert 'Staples Inc' in call_args
    
    def test_should_use_llm_high_confidence(self, mock_settings, mock_supabase):
        """Test routing with high confidence score."""
        with patch('app.services.mapper_agent.OpenAIEmbeddings'):
            with patch('app.services.mapper_agent.ChatOpenAI'):
                service = MapperAgentService()
                
                state: TransactionState = {
                    'transaction_id': 'test-id',
                    'deal_id': 'deal-id',
                    'raw_account': '',
                    'raw_desc': '',
                    'vendor': '',
                    'amount': '100',
                    'embedding': [0.1] * 1536,
                    'similarity_score': 0.95,
                    'matched_coa_id': 'coa-id',
                    'matched_coa_name': 'Test COA',
                    'confidence': 0.95,
                    'mapping_source': 'vector_search',
                    'llm_reasoning': None,
                    'needs_llm': False,
                    'is_complete': True,
                    'error': None
                }
                
                result = service.should_use_llm(state)
                assert result == 'end'
    
    def test_should_use_llm_low_confidence(self, mock_settings, mock_supabase):
        """Test routing with low confidence score."""
        with patch('app.services.mapper_agent.OpenAIEmbeddings'):
            with patch('app.services.mapper_agent.ChatOpenAI'):
                service = MapperAgentService()
                
                state: TransactionState = {
                    'transaction_id': 'test-id',
                    'deal_id': 'deal-id',
                    'raw_account': '',
                    'raw_desc': '',
                    'vendor': '',
                    'amount': '100',
                    'embedding': [0.1] * 1536,
                    'similarity_score': 0.75,
                    'matched_coa_id': None,
                    'matched_coa_name': None,
                    'confidence': None,
                    'mapping_source': None,
                    'llm_reasoning': None,
                    'needs_llm': True,
                    'is_complete': False,
                    'error': None
                }
                
                result = service.should_use_llm(state)
                assert result == 'llm'


class TestMapperAgentIntegration:
    """Integration tests for mapper agent (require mocked external services)."""
    
    @pytest.fixture
    def mock_all_deps(self):
        """Mock all external dependencies."""
        with patch('app.services.mapper_agent.get_settings') as mock_settings, \
             patch('app.services.mapper_agent.get_supabase_admin_client') as mock_supabase, \
             patch('app.services.mapper_agent.OpenAIEmbeddings') as mock_embeddings, \
             patch('app.services.mapper_agent.ChatOpenAI') as mock_llm:
            
            settings = Mock()
            settings.openai_api_key = 'test-key'
            settings.openai_embedding_model = 'text-embedding-3-small'
            settings.openai_chat_model = 'gpt-4o'
            settings.mapper_auto_threshold = 0.92
            settings.mapper_min_threshold = 0.5
            mock_settings.return_value = settings
            
            client = MagicMock()
            mock_supabase.return_value = client
            
            embed_instance = Mock()
            embed_instance.embed_query.return_value = [0.1] * 1536
            mock_embeddings.return_value = embed_instance
            
            llm_instance = Mock()
            mock_llm.return_value = llm_instance
            
            yield {
                'settings': settings,
                'client': client,
                'embeddings': embed_instance,
                'llm': llm_instance
            }
    
    def test_process_transaction_auto_map(self, mock_all_deps):
        """Test processing a transaction that auto-maps."""
        # Configure mock to return high-similarity match
        mock_all_deps['client'].rpc.return_value.execute.return_value.data = [{
            'id': 'match-id',
            'mapped_coa_id': 'coa-123',
            'coa_name': 'Office Supplies',
            'similarity': 0.95
        }]
        
        mock_all_deps['client'].table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {'id': 'coa-123', 'category': 'Operating Expenses', 'account_name': 'Office Supplies'}
        ]
        
        service = MapperAgentService()
        
        transaction = {
            'id': 'tx-123',
            'deal_id': 'deal-456',
            'raw_account': '6100',
            'raw_desc': 'Office supplies from Staples',
            'vendor': 'Staples',
            'amount': '150.00'
        }
        
        result = service.process_transaction(transaction)
        
        # Should auto-map due to high similarity
        assert result.get('matched_coa_id') is not None
        assert result.get('mapping_source') == 'vector_search'
