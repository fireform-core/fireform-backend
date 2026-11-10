import pytest
from fastapi.testclient import TestClient

from app.core.config import API_PREFIX
from app.main import app
from app.api.middleware.rate_limiter import limiter

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_limiter():
    """Turn on and clean the rate limiter only for the tests in this file."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False


def test_rate_limit_forms_fill():
    """Test that the /forms/fill endpoint blocks requests after 20 hits per minute."""
    endpoint = f"{API_PREFIX}/forms/fill"
    payload = {"template_id": 1}
    
    for _ in range(20):
        response = client.post(endpoint, json=payload)
        assert response.status_code != 429
        
    response = client.post(endpoint, json=payload)
    assert response.status_code == 429
    
    data = response.json()
    assert data["error_code"] == "RATE_LIMIT_EXCEEDED"
    assert "20 per 1 minute" in data["message"]
    # Same envelope as AppError, plus when to try again
    assert "success" not in data and "error" not in data
    assert 1 <= data["retry_after_seconds"] <= 60
    assert response.headers["Retry-After"] == str(data["retry_after_seconds"])


def test_rate_limit_templates_upload():
    """Test that the /templates/upload endpoint blocks requests after 10 hits per minute."""
    endpoint = f"{API_PREFIX}/templates/upload"
    
    files = {"file": ("dummy.pdf", b"dummy content", "application/pdf")}
    
    for _ in range(10):
        response = client.post(endpoint, files=files)
        assert response.status_code != 429
        
    response = client.post(endpoint, files=files)
    assert response.status_code == 429
    
    data = response.json()
    assert "10 per 1 minute" in data["message"]


def test_rate_limit_templates_list():
    """Test that the /templates endpoint blocks GET requests after 10 hits per minute."""
    endpoint = f"{API_PREFIX}/templates"
    
    for _ in range(10):
        response = client.get(endpoint)
        assert response.status_code != 429
        
    response = client.get(endpoint)
    assert response.status_code == 429
    
    data = response.json()
    assert "10 per 1 minute" in data["message"]