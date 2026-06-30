import json
import hmac
import hashlib
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from main import app
from app.config import settings
from app.utils.rate_limiter import rate_limiter
from app.database.mongodb import mongodb

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_context():
    # Save original configurations
    orig_verify_token = settings.instagram_verify_token
    orig_app_secret = settings.instagram_app_secret
    orig_rate_limit_calls = settings.rate_limit_calls
    orig_rate_limit_period = settings.rate_limit_period_seconds
    
    # Clear rate limiter cache
    rate_limiter.requests.clear()
    
    # Mock MongoDB connection and storage methods to prevent network hits
    mock_connect = AsyncMock()
    mock_close = AsyncMock()
    mock_save = AsyncMock(return_value="mocked_document_id_5678")
    
    with patch.object(mongodb, "connect", mock_connect), \
         patch.object(mongodb, "close", mock_close), \
         patch.object(mongodb, "save_webhook_payload", mock_save):
        yield
        
    # Restore original configurations
    settings.instagram_verify_token = orig_verify_token
    settings.instagram_app_secret = orig_app_secret
    settings.rate_limit_calls = orig_rate_limit_calls
    settings.rate_limit_period_seconds = orig_rate_limit_period
    rate_limiter.requests.clear()


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "instagram-webhook-backend"


def test_webhook_verification_success():
    settings.instagram_verify_token = "verify_secret_123"
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify_secret_123",
            "hub.challenge": "challenge_token_456"
        }
    )
    assert response.status_code == 200
    assert response.text == "challenge_token_456"


def test_webhook_verification_failure():
    settings.instagram_verify_token = "verify_secret_123"
    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "incorrect_verify_token",
            "hub.challenge": "challenge_token_456"
        }
    )
    assert response.status_code == 403


def test_webhook_post_success_no_signature_needed_for_mock():
    settings.instagram_app_secret = "mock_app_secret"
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "instagram_biz_account_id",
                "time": 1600000000,
                "messaging": [
                    {
                        "sender": {"id": "user_psid_1"},
                        "recipient": {"id": "page_id_2"},
                        "timestamp": 1600000000,
                        "message": {
                            "mid": "mid.test_msg_id",
                            "text": "hello antigravity"
                        }
                    }
                ]
            }
        ]
    }
    response = client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "EVENT_RECEIVED"}


def test_webhook_post_with_valid_signature():
    settings.instagram_app_secret = "secret_key_123"
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "instagram_biz_account_id",
                "time": 1600000000,
                "messaging": [
                    {
                        "sender": {"id": "user_psid_1"},
                        "recipient": {"id": "page_id_2"},
                        "timestamp": 1600000000,
                        "message": {
                            "mid": "mid.test_msg_id_2",
                            "text": "image"
                        }
                    }
                ]
            }
        ]
    }
    
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    computed_sig = hmac.new(
        key=b"secret_key_123",
        msg=payload_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()
    
    response = client.post(
        "/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={computed_sig}"
        }
    )
    assert response.status_code == 200
    assert response.json() == {"status": "EVENT_RECEIVED"}


def test_webhook_post_with_invalid_signature():
    settings.instagram_app_secret = "secret_key_123"
    payload = {
        "object": "instagram",
        "entry": []
    }
    
    payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    
    response = client.post(
        "/webhook",
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=invalid_signature_hex_value"
        }
    )
    assert response.status_code == 401


def test_rate_limiting_blocking():
    # Set tight limits: max 2 calls in 10 seconds
    settings.rate_limit_calls = 2
    settings.rate_limit_period_seconds = 10
    settings.instagram_verify_token = "verify_secret_123"
    
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "verify_secret_123",
        "hub.challenge": "challenge_token_456"
    }
    
    # 1st request - should pass
    res1 = client.get("/webhook", params=params)
    assert res1.status_code == 200
    
    # 2nd request - should pass
    res2 = client.get("/webhook", params=params)
    assert res2.status_code == 200
    
    # 3rd request - should be blocked by rate limit
    res3 = client.get("/webhook", params=params)
    assert res3.status_code == 429
    assert res3.json()["detail"] == "Too many requests. Please try again later."
