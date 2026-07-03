import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel
from app.database.mongodb import mongodb
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

class AccountCreate(BaseModel):
    instagram_business_id: str
    page_access_token: str

@router.get("/stats")
async def get_stats():
    stats = await mongodb.get_dashboard_stats()
    stats["verify_token"] = settings.instagram_verify_token
    stats["api_version"] = settings.instagram_api_version
    return stats

@router.get("/accounts")
async def get_accounts():
    accounts = await mongodb.get_all_page_access_tokens()
    return accounts

@router.post("/accounts")
async def create_account(account: AccountCreate):
    if not account.instagram_business_id.strip() or not account.page_access_token.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="instagram_business_id and page_access_token are required"
        )
    await mongodb.save_page_access_token(
        business_id=account.instagram_business_id.strip(),
        page_access_token=account.page_access_token.strip()
    )
    return {"status": "success", "message": "Account token saved successfully"}

@router.delete("/accounts/{business_id}")
async def delete_account(business_id: str):
    deleted = await mongodb.delete_page_access_token(business_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or could not be deleted"
        )
    return {"status": "success", "message": "Account token deleted successfully"}

@router.get("/users")
async def get_users():
    users = await mongodb.get_instagram_users()
    return users

@router.get("/users/{user_id}/chat")
async def get_user_chat(user_id: str):
    chat_history = await mongodb.get_chat_history(user_id)
    return chat_history

@router.get("/payloads")
async def get_payloads(limit: int = Query(default=50, ge=1, le=100)):
    payloads = await mongodb.get_recent_payloads(limit=limit)
    return payloads
