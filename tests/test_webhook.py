import json
import hmac
import hashlib
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from app.config import settings
from app.utils.rate_limiter import rate_limiter
from app.database.mongodb import mongodb
from app.services.webhook_queue import webhook_queue

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
    mock_enqueue = AsyncMock()
    
    with patch.object(mongodb, "connect", mock_connect), \
         patch.object(mongodb, "close", mock_close), \
         patch.object(mongodb, "save_webhook_payload", mock_save), \
         patch.object(webhook_queue, "enqueue", mock_enqueue):
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
    assert "<!DOCTYPE html>" in response.text

    response = client.get("/api/health")
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


@pytest.mark.asyncio
async def test_webhook_queue_processing_and_idempotency():
    from app.services.webhook_queue import WebhookQueue
    from app.services.instagram import instagram_service
    
    # Instantiate a clean queue for testing
    queue = WebhookQueue()
    
    # Mock methods on mongodb and instagram_service
    mock_is_processed = AsyncMock(side_effect=lambda mid: mid == "duplicate_mid")
    mock_mark_processed = AsyncMock()
    mock_update_status = AsyncMock()
    mock_get_token = AsyncMock(return_value="mock_saas_page_access_token")
    mock_handle_message = AsyncMock()
    
    with patch.object(mongodb, "is_event_processed", mock_is_processed), \
         patch.object(mongodb, "mark_event_processed", mock_mark_processed), \
         patch.object(mongodb, "update_payload_status", mock_update_status), \
         patch.object(mongodb, "get_page_access_token", mock_get_token), \
         patch.object(instagram_service, "handle_message_event", mock_handle_message):
         
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "entry_id",
                    "time": 12345,
                    "messaging": [
                        {
                            "sender": {"id": "sender_1"},
                            "recipient": {"id": "receiver_1"},
                            "timestamp": 12345,
                            "message": {
                                "mid": "unique_mid_1",
                                "text": "hello"
                            }
                        },
                        {
                            "sender": {"id": "sender_1"},
                            "recipient": {"id": "receiver_1"},
                            "timestamp": 12345,
                            "message": {
                                "mid": "duplicate_mid",
                                "text": "should be skipped"
                            }
                        }
                    ]
                }
            ]
        }
        
        # Test processing of the payload
        await queue._process_payload("test_payload_id", payload)
        
        # Verify status updates on the payload
        mock_update_status.assert_any_call("test_payload_id", "processing")
        mock_update_status.assert_any_call("test_payload_id", "processed")
        
        # Verify handle_message_event called only for unique_mid_1, not duplicate_mid
        mock_handle_message.assert_called_once_with(
            "sender_1",
            {"mid": "unique_mid_1", "text": "hello", "is_echo": False},
            access_token="mock_saas_page_access_token"
        )
        
        # Verify mark_event_processed was called for the processed event
        mock_mark_processed.assert_called_once_with("unique_mid_1")


@pytest.mark.asyncio
async def test_webhook_queue_recovery_on_startup():
    from app.services.webhook_queue import WebhookQueue
    import asyncio
    
    queue = WebhookQueue()
    
    # Mock database to return some pending items
    mock_get_pending = AsyncMock(return_value=[
        {"_id": "pending_id_1", "payload": {"object": "instagram", "entry": []}}
    ])
    
    with patch.object(mongodb, "get_pending_payloads", mock_get_pending):
        # We start the queue, but we don't start the full worker loop to keep the test simple, 
        # or we mock it. We can mock asyncio.create_task to return an awaitable asyncio.Future.
        mock_task = asyncio.Future()
        with patch("asyncio.create_task", return_value=mock_task) as mock_create_task:
            await queue.start()
            
            # Assert get_pending_payloads was called
            mock_get_pending.assert_called_once()
            
            # Assert queue has the pending item
            assert queue._queue.qsize() == 1
            item = await queue._queue.get()
            assert item == ("pending_id_1", {"object": "instagram", "entry": []})
            
            # Close the unawaited worker loop coroutine to suppress python warnings
            coro = mock_create_task.call_args[0][0]
            coro.close()
            
            # Stop clean up
            await queue.stop()


@pytest.mark.asyncio
async def test_webhook_queue_processing_all_new_events():
    from app.services.webhook_queue import WebhookQueue
    from app.services.instagram import instagram_service
    
    queue = WebhookQueue()
    
    mock_is_processed = AsyncMock(return_value=False)
    mock_mark_processed = AsyncMock()
    mock_update_status = AsyncMock()
    mock_get_token = AsyncMock(return_value="mock_saas_page_access_token")
    mock_handle_read = MagicMock()
    mock_handle_reaction = AsyncMock()
    mock_handle_referral = AsyncMock()
    mock_handle_optin = AsyncMock()
    
    with patch.object(mongodb, "is_event_processed", mock_is_processed), \
         patch.object(mongodb, "mark_event_processed", mock_mark_processed), \
         patch.object(mongodb, "update_payload_status", mock_update_status), \
         patch.object(mongodb, "get_page_access_token", mock_get_token), \
         patch.object(instagram_service, "handle_read_event", mock_handle_read), \
         patch.object(instagram_service, "handle_reaction_event", mock_handle_reaction), \
         patch.object(instagram_service, "handle_referral_event", mock_handle_referral), \
         patch.object(instagram_service, "handle_optin_event", mock_handle_optin):
         
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "entry_id",
                    "time": 12345,
                    "messaging": [
                        {
                            "sender": {"id": "sender_1"},
                            "recipient": {"id": "receiver_1"},
                            "timestamp": 12345,
                            "read": {"watermark": 1600000000, "mid": "mid.read_msg"}
                        },
                        {
                            "sender": {"id": "sender_1"},
                            "recipient": {"id": "receiver_1"},
                            "timestamp": 12345,
                            "reaction": {"mid": "mid.reacted_msg", "action": "react", "emoji": "❤️", "reaction": "love"}
                        },
                        {
                            "sender": {"id": "sender_1"},
                            "recipient": {"id": "receiver_1"},
                            "timestamp": 12345,
                            "referral": {"ref": "ref_code_123", "source": "SHORTLINK", "type": "OPEN_THREAD"}
                        },
                        {
                            "sender": {"id": "sender_1"},
                            "recipient": {"id": "receiver_1"},
                            "timestamp": 12345,
                            "optin": {"ref": "optin_ref_456"}
                        }
                    ]
                }
            ]
        }
        
        await queue._process_payload("test_payload_id", payload)
        
        mock_handle_read.assert_called_once_with(
            "sender_1",
            {"watermark": 1600000000, "mid": "mid.read_msg"}
        )
        mock_handle_reaction.assert_called_once_with(
            "sender_1",
            {"mid": "mid.reacted_msg", "action": "react", "emoji": "❤️", "reaction": "love"},
            access_token="mock_saas_page_access_token"
        )
        mock_handle_referral.assert_called_once_with(
            "sender_1",
            {"ref": "ref_code_123", "source": "SHORTLINK", "type": "OPEN_THREAD"},
            access_token="mock_saas_page_access_token"
        )
        mock_handle_optin.assert_called_once_with(
            "sender_1",
            {"ref": "optin_ref_456"},
            access_token="mock_saas_page_access_token"
        )


@pytest.mark.asyncio
async def test_webhook_queue_user_tracking():
    from app.services.webhook_queue import WebhookQueue
    from app.services.instagram import instagram_service
    
    queue = WebhookQueue()
    
    # Test 1: New user (should fetch profile and upsert)
    mock_get_user = AsyncMock(return_value=None)
    mock_upsert_user = AsyncMock()
    mock_get_profile = AsyncMock(return_value={"name": "Alice", "profile_pic": "alice.jpg"})
    
    # Minimal message payload
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "biz_1",
                "time": 12345,
                "messaging": [
                    {
                        "sender": {"id": "user_alice"},
                        "recipient": {"id": "receiver_1"},
                        "timestamp": 12345,
                        "message": {
                            "mid": "mid_alice_1",
                            "text": "hello"
                        }
                    }
                ]
            }
        ]
    }
    
    with patch.object(mongodb, "get_instagram_user", mock_get_user), \
         patch.object(mongodb, "upsert_instagram_user", mock_upsert_user), \
         patch.object(mongodb, "is_event_processed", AsyncMock(return_value=False)), \
         patch.object(mongodb, "mark_event_processed", AsyncMock()), \
         patch.object(mongodb, "update_payload_status", AsyncMock()), \
         patch.object(mongodb, "get_page_access_token", AsyncMock(return_value="mock_token")), \
         patch.object(instagram_service, "get_user_profile", mock_get_profile), \
         patch.object(instagram_service, "handle_message_event", AsyncMock()):
         
        await queue._process_payload("payload_id_1", payload)
        
        # Verify first-time user fetches profile and upserts
        mock_get_user.assert_called_once_with("user_alice")
        mock_get_profile.assert_called_once_with("user_alice", "mock_token")
        mock_upsert_user.assert_called_once_with("biz_1", "user_alice", {"name": "Alice", "profile_pic": "alice.jpg"})
        
    # Test 2: Existing cached user (should NOT fetch profile, only upsert)
    from datetime import datetime, timezone
    mock_get_user_cached = AsyncMock(return_value={
        "instagram_user_id": "user_alice",
        "last_seen_at": datetime.now(timezone.utc)
    })
    mock_upsert_user_cached = AsyncMock()
    mock_get_profile_cached = AsyncMock()
    
    with patch.object(mongodb, "get_instagram_user", mock_get_user_cached), \
         patch.object(mongodb, "upsert_instagram_user", mock_upsert_user_cached), \
         patch.object(mongodb, "is_event_processed", AsyncMock(return_value=False)), \
         patch.object(mongodb, "mark_event_processed", AsyncMock()), \
         patch.object(mongodb, "update_payload_status", AsyncMock()), \
         patch.object(mongodb, "get_page_access_token", AsyncMock(return_value="mock_token")), \
         patch.object(instagram_service, "get_user_profile", mock_get_profile_cached), \
         patch.object(instagram_service, "handle_message_event", AsyncMock()):
         
        await queue._process_payload("payload_id_2", payload)
        
        # Verify cached user does NOT call get_user_profile, but still calls upsert to update last_seen_at
        mock_get_user_cached.assert_called_once_with("user_alice")
        mock_get_profile_cached.assert_not_called()
        mock_upsert_user_cached.assert_called_once_with("biz_1", "user_alice", None)


@pytest.mark.asyncio
async def test_webhook_queue_activity_logging():
    from app.services.webhook_queue import WebhookQueue
    from app.services.instagram import instagram_service
    
    queue = WebhookQueue()
    
    # Mock log_user_activity and other DB / service calls
    mock_log_activity = AsyncMock()
    
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "biz_1",
                "time": 12345,
                "messaging": [
                    {
                        "sender": {"id": "user_123"},
                        "recipient": {"id": "biz_1"},
                        "timestamp": 1600000000,
                        "message": {
                            "mid": "mid_activity_1",
                            "text": "hello chatbot"
                        }
                    }
                ]
            }
        ]
    }
    
    with patch.object(mongodb, "log_user_activity", mock_log_activity), \
         patch.object(mongodb, "is_event_processed", AsyncMock(return_value=False)), \
         patch.object(mongodb, "mark_event_processed", AsyncMock()), \
         patch.object(mongodb, "update_payload_status", AsyncMock()), \
         patch.object(mongodb, "get_page_access_token", AsyncMock(return_value="mock_token")), \
         patch.object(mongodb, "get_instagram_user", AsyncMock(return_value=None)), \
         patch.object(mongodb, "upsert_instagram_user", AsyncMock()), \
         patch.object(instagram_service, "get_user_profile", AsyncMock()), \
         patch.object(instagram_service, "handle_message_event", AsyncMock()):
         
        await queue._process_payload("payload_activity_1", payload)
        
        # Verify log_user_activity is called correctly
        mock_log_activity.assert_called_once_with(
            "biz_1",
            "user_123",
            "message",
            1600000000,
            {"mid": "mid_activity_1", "text": "hello chatbot", "is_echo": False}
        )


