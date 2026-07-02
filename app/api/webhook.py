import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Request, Query, Header, HTTPException, status, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from app.config import settings
from app.utils.security import verify_signature
from app.utils.rate_limiter import rate_limiter, get_client_ip
from app.database.mongodb import mongodb
from app.services.webhook_queue import webhook_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

@router.get("", response_class=PlainTextResponse, dependencies=[Depends(rate_limiter.check_rate_limit)])
async def verify_webhook(
    request: Request,
    mode: Annotated[Optional[str], Query(alias="hub.mode")] = None,
    verify_token: Annotated[Optional[str], Query(alias="hub.verify_token")] = None,
    challenge: Annotated[Optional[str], Query(alias="hub.challenge")] = None
):
    """
    Endpoint for Meta webhook verification.
    """
    client_ip = get_client_ip(request)
    logger.info(f"Verification request received from IP: {client_ip}. mode={mode}, token={verify_token}")
    
    if mode == "subscribe" and verify_token == settings.instagram_verify_token:
        logger.info("Webhook verification succeeded.")
        return challenge
        
    logger.error("Webhook verification failed: Invalid token or mode mismatch.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch or invalid mode"
    )


@router.post("", dependencies=[Depends(rate_limiter.check_rate_limit)])
async def receive_webhook(
    request: Request,
    x_hub_signature_256: Annotated[Optional[str], Header(alias="X-Hub-Signature-256")] = None
):
    """
    Endpoint for receiving Meta webhook event payloads.
    """
    client_ip = get_client_ip(request)
    logger.info(f"Received webhook request from IP: {client_ip}")
    
    body = await request.body()
    
    if settings.instagram_app_secret != "mock_app_secret" or x_hub_signature_256:
        is_valid = verify_signature(
            payload=body,
            signature_header=x_hub_signature_256 or "",
            secret=settings.instagram_app_secret
        )
        if not is_valid:
            logger.warning("Unauthorized webhook payload received. Signature mismatch.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Signature verification failed"
            )
            
    try:
        payload_dict = await request.json()
    except Exception:
        logger.exception("Failed to parse request JSON")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body"
        )
        
    payload_id = await mongodb.save_webhook_payload(payload_dict, client_ip)
    if payload_id:
        await webhook_queue.enqueue(payload_id, payload_dict)
    else:
        logger.error("Could not persist webhook payload; queuing skipped.")
    
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "EVENT_RECEIVED"})
