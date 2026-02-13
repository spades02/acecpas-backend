"""
Tests for API Endpoints
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from uuid import uuid4

from app.main import app


client = TestClient(app)


class TestHealthEndpoints:
    """Test health and root endpoints."""
    
    def test_health_check(self):
        """Test health endpoint returns OK."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    def test_root_endpoint(self):
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "AceCPAs Backend API"
        assert "version" in data


class TestUploadEndpoints:
    """Test file upload endpoints."""
    
    @pytest.fixture
    def mock_supabase(self):
        """Mock Supabase for upload tests."""
        with patch('app.routers.upload.get_supabase_admin_client') as mock:
            client = MagicMock()
            mock.return_value = client
            
            # Mock storage
            storage = MagicMock()
            client.storage.from_.return_value = storage
            
            # Mock table insert
            client.table.return_value.insert.return_value.execute.return_value.data = [{
                'id': str(uuid4()),
                'deal_id': str(uuid4()),
                'file_name': 'test.xlsx',
                'status': 'pending'
            }]
            
            yield client
    
    @pytest.fixture
    def mock_celery(self):
        """Mock Celery task."""
        with patch('app.routers.upload.process_gl_file') as mock:
            mock.delay.return_value = None
            yield mock
    
    def test_upload_invalid_file_type(self):
        """Test upload rejects invalid file types."""
        response = client.post(
            "/upload",
            params={"deal_id": str(uuid4())},
            files={"file": ("test.pdf", b"fake content", "application/pdf")}
        )
        assert response.status_code == 400
        assert "Invalid file type" in response.json()["detail"]
    
    def test_upload_empty_file(self, mock_supabase, mock_celery):
        """Test upload rejects empty files."""
        response = client.post(
            "/upload",
            params={"deal_id": str(uuid4())},
            files={"file": ("test.xlsx", b"", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
        assert response.status_code == 400
        assert "Empty file" in response.json()["detail"]


class TestDealsEndpoints:
    """Test deals endpoints."""
    
    @pytest.fixture
    def mock_supabase(self):
        """Mock Supabase for deals tests."""
        with patch('app.routers.deals.get_supabase_admin_client') as mock:
            client = MagicMock()
            mock.return_value = client
            yield client
    
    def test_list_deals(self, mock_supabase):
        """Test listing deals."""
        mock_supabase.table.return_value.select.return_value.order.return_value.execute.return_value.data = [
            {
                'id': str(uuid4()),
                'org_id': str(uuid4()),
                'client_name': 'Test Client',
                'status': 'active',
                'created_at': '2024-01-01T00:00:00Z',
                'updated_at': '2024-01-01T00:00:00Z'
            }
        ]
        
        response = client.get("/deals")
        assert response.status_code == 200
        assert len(response.json()) == 1
    
    def test_get_deal_stats(self, mock_supabase):
        """Test getting deal statistics."""
        deal_id = str(uuid4())
        
        # Mock all stat queries
        mock_query = MagicMock()
        mock_query.count = 100
        mock_query.data = []
        
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_query
        mock_supabase.table.return_value.select.return_value.eq.return_value.not_.is_.return_value.execute.return_value = mock_query
        mock_supabase.table.return_value.select.return_value.eq.return_value.lt.return_value.execute.return_value = mock_query
        mock_supabase.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value = mock_query
        
        response = client.get(f"/deals/{deal_id}/stats")
        assert response.status_code == 200


class TestOpenItemsEndpoints:
    """Test open items endpoints."""
    
    @pytest.fixture
    def mock_supabase(self):
        """Mock Supabase for open items tests."""
        with patch('app.routers.open_items.get_supabase_admin_client') as mock:
            client = MagicMock()
            mock.return_value = client
            yield client
    
    def test_list_open_items(self, mock_supabase):
        """Test listing open items."""
        deal_id = str(uuid4())
        
        mock_supabase.table.return_value.select.return_value.eq.return_value.neq.return_value.order.return_value.execute.return_value.data = [
            {
                'id': str(uuid4()),
                'deal_id': deal_id,
                'question_text': 'Test question',
                'status': 'draft',
                'gl_transactions': None,
                'created_at': '2024-01-01T00:00:00Z',
                'updated_at': '2024-01-01T00:00:00Z'
            }
        ]
        
        response = client.get(f"/deals/{deal_id}/open-items")
        assert response.status_code == 200
