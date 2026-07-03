import logging
import base64
import hashlib
import hmac
import httpx
import json
import secrets
import urllib.parse
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Query, Request, Form
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from app.database.mongodb import mongodb
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

class AccountCreate(BaseModel):
    instagram_business_id: str
    page_access_token: str


class AccountUpdate(BaseModel):
    account_status: Optional[str] = None
    subscription_status: Optional[str] = None
    notes: Optional[str] = None


OAUTH_SCOPES = {
    "instagram": [
        "instagram_business_basic",
        "instagram_business_manage_messages",
        "instagram_business_manage_comments"
    ],
    "facebook": [
        "pages_show_list",
        "instagram_basic",
        "instagram_manage_messages",
        "pages_read_engagement",
        "pages_manage_metadata"
    ]
}


def _oauth_redirect_uri(request: Request) -> str:
    if settings.oauth_redirect_uri:
        return settings.oauth_redirect_uri
    if settings.backend_public_url:
        return f"{settings.backend_public_url.rstrip('/')}/api/admin/oauth/callback"
    return str(request.url_for("oauth_callback"))


def _oauth_authorize_url(platform: str) -> str:
    if platform == "instagram":
        return settings.instagram_oauth_base_url
    return f"{settings.facebook_oauth_base_url.rstrip('/')}/{settings.instagram_api_version}/dialog/oauth"


def _mask_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return token
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _sanitize_account(account: dict) -> dict:
    sanitized = dict(account)
    if "page_access_token" in sanitized:
        sanitized["page_access_token_preview"] = _mask_token(sanitized.get("page_access_token"))
        sanitized.pop("page_access_token", None)
    return sanitized


def _sanitize_meta_user(user: dict) -> dict:
    sanitized = dict(user)
    if "user_access_token" in sanitized:
        sanitized["user_access_token_preview"] = _mask_token(sanitized.get("user_access_token"))
        sanitized.pop("user_access_token", None)
    return sanitized


@router.get("/oauth-url")
async def get_oauth_url(
    request: Request,
    platform: str = "instagram",
    state: Optional[str] = None
):
    if not settings.instagram_app_id or settings.instagram_app_id == "mock_app_id":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meta App ID is not configured on the server."
        )

    platform_key = platform.lower()
    if platform_key not in OAUTH_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported OAuth platform."
        )

    params = {
        "client_id": settings.instagram_app_id,
        "redirect_uri": _oauth_redirect_uri(request),
        "scope": ",".join(OAUTH_SCOPES[platform_key]),
        "response_type": "code"
    }
    if state:
        params["state"] = state

    url = f"{_oauth_authorize_url(platform_key)}?{urllib.parse.urlencode(params)}"
    return {"url": url}


@router.get("/auth/login")
async def login_user(request: Request, platform: str = "facebook", state: Optional[str] = None):
    """
    Generate the Meta OAuth login URL for connecting a user and their Pages.
    """
    return await get_oauth_url(request=request, platform=platform, state=state)


@router.get("/oauth/callback", name="oauth_callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None
):
    """
    Backend OAuth redirect endpoint for Meta Login.

    Meta redirects here with a short-lived `code`. We immediately exchange it
    server-side, save Page access tokens keyed by Instagram business account ID,
    subscribe the connected Pages to webhook events, then send the browser back
    to the frontend dashboard.
    """
    frontend_url = settings.frontend_dashboard_url
    if error:
        params = urllib.parse.urlencode({
            "connected": "0",
            "error": error_description or error
        })
        return RedirectResponse(f"{frontend_url}?{params}", status_code=status.HTTP_302_FOUND)

    if not code:
        params = urllib.parse.urlencode({
            "connected": "0",
            "error": "Missing OAuth code from Meta."
        })
        return RedirectResponse(f"{frontend_url}?{params}", status_code=status.HTTP_302_FOUND)

    if (
        not settings.instagram_app_id
        or settings.instagram_app_id == "mock_app_id"
        or not settings.instagram_app_secret
        or settings.instagram_app_secret == "mock_app_secret"
    ):
        params = urllib.parse.urlencode({
            "connected": "0",
            "error": "Meta App ID or App Secret is not configured on the server."
        })
        return RedirectResponse(f"{frontend_url}?{params}", status_code=status.HTTP_302_FOUND)

    try:
        connected_accounts = await _connect_meta_accounts(code, _oauth_redirect_uri(request))
    except Exception as exc:
        logger.exception("OAuth callback failed while connecting Meta accounts.")
        params = urllib.parse.urlencode({
            "connected": "0",
            "error": str(exc)
        })
        return RedirectResponse(f"{frontend_url}?{params}", status_code=status.HTTP_302_FOUND)

    params = urllib.parse.urlencode({
        "connected": "1",
        "accounts": str(len(connected_accounts))
    })
    return RedirectResponse(f"{frontend_url}?{params}", status_code=status.HTTP_302_FOUND)


async def _connect_meta_accounts(code: str, redirect_uri: str) -> list[dict]:
    graph_base_url = f"{settings.graph_api_base_url.rstrip('/')}/{settings.instagram_api_version}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.get(
            f"{graph_base_url}/oauth/access_token",
            params={
                "client_id": settings.instagram_app_id,
                "client_secret": settings.instagram_app_secret,
                "redirect_uri": redirect_uri,
                "code": code
            }
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        user_access_token = token_data.get("access_token")
        if not user_access_token:
            raise RuntimeError("Meta did not return a user access token.")

        user_profile_response = await client.get(
            f"{graph_base_url}/me",
            params={
                "fields": "id,name,email",
                "access_token": user_access_token
            }
        )
        user_profile_response.raise_for_status()
        user_profile = user_profile_response.json()
        meta_user_id = user_profile.get("id")
        if meta_user_id:
            await mongodb.save_meta_user_profile(
                meta_user_id=meta_user_id,
                name=user_profile.get("name"),
                email=user_profile.get("email"),
                user_access_token=user_access_token,
                token_expires_in=token_data.get("expires_in"),
                auth_status="active"
            )

        pages_response = await client.get(
            f"{graph_base_url}/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account{id,username}",
                "access_token": user_access_token
            }
        )
        pages_response.raise_for_status()
        pages = pages_response.json().get("data", [])

        connected_accounts = []
        for page in pages:
            page_id = page.get("id")
            page_access_token = page.get("access_token")
            instagram_account = page.get("instagram_business_account") or {}
            instagram_business_id = instagram_account.get("id")
            instagram_username = instagram_account.get("username")

            if not page_id or not page_access_token or not instagram_business_id:
                logger.info("Skipping Page without complete Instagram connection data: %s", page)
                continue

            subscribed_fields = [
                "messages",
                "messaging_postbacks",
                "messaging_seen",
                "messaging_reactions"
            ]
            subscription_response = await client.post(
                f"{graph_base_url}/{page_id}/subscribed_apps",
                params={
                    "subscribed_fields": ",".join(subscribed_fields),
                    "access_token": page_access_token
                }
            )
            subscription_response.raise_for_status()

            await mongodb.save_page_access_token(
                business_id=instagram_business_id,
                page_access_token=page_access_token,
                page_id=page_id,
                page_name=page.get("name"),
                meta_user_id=meta_user_id,
                instagram_username=instagram_username,
                subscribed_fields=subscribed_fields,
                subscription_status="subscribed",
                account_status="active"
            )

            connected_accounts.append({
                "page_id": page_id,
                "page_name": page.get("name"),
                "meta_user_id": meta_user_id,
                "instagram_business_id": instagram_business_id,
                "instagram_username": instagram_username,
                "subscription_status": "subscribed",
                "account_status": "active"
            })

        if not connected_accounts:
            raise RuntimeError("No connected Instagram business accounts were found for this Meta login.")

        return connected_accounts

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


@router.get("/connected-accounts")
async def get_connected_accounts(include_tokens: bool = False):
    accounts = await mongodb.get_all_page_access_tokens()
    if include_tokens:
        return accounts
    return [_sanitize_account(account) for account in accounts]


@router.get("/connected-accounts/{business_id}")
async def get_connected_account(business_id: str, include_tokens: bool = False):
    account = await mongodb.get_connected_account(business_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected account not found"
        )
    return account if include_tokens else _sanitize_account(account)


@router.patch("/connected-accounts/{business_id}")
async def update_connected_account(business_id: str, account: AccountUpdate):
    update_fields = account.model_dump(exclude_none=True)
    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No account fields provided for update"
        )

    updated = await mongodb.update_connected_account(business_id, update_fields)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected account not found or unchanged"
        )
    return {"status": "success", "message": "Connected account updated successfully"}


@router.post("/connected-accounts/{business_id}/deauthorize")
async def deauthorize_connected_account(business_id: str):
    account = await mongodb.get_connected_account(business_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected account not found"
        )

    page_id = account.get("page_id")
    page_access_token = account.get("page_access_token")
    if not page_id or not page_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connected account is missing page_id or page_access_token"
        )

    graph_base_url = f"{settings.graph_api_base_url.rstrip('/')}/{settings.instagram_api_version}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(
            f"{graph_base_url}/{page_id}/subscribed_apps",
            params={"access_token": page_access_token}
        )
        response.raise_for_status()

    await mongodb.update_connected_account(
        business_id,
        {
            "subscription_status": "deauthorized",
            "account_status": "inactive"
        }
    )

    meta_user_id = account.get("meta_user_id")
    if meta_user_id:
        remaining_accounts = await mongodb.get_accounts_by_meta_user(meta_user_id)
        active_remaining = [
            item for item in remaining_accounts
            if item.get("instagram_business_id") != business_id
            and item.get("account_status") == "active"
        ]
        if not active_remaining:
            await mongodb.update_meta_user_status(meta_user_id, "deauthorized")

    return {"status": "success", "message": "Connected account deauthorized successfully"}


@router.delete("/connected-accounts/{business_id}")
async def delete_connected_account(business_id: str, deauthorize: bool = False):
    if deauthorize:
        await deauthorize_connected_account(business_id)

    deleted = await mongodb.delete_page_access_token(business_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected account not found or could not be deleted"
        )
    return {"status": "success", "message": "Connected account deleted successfully"}


@router.get("/meta-users")
async def get_meta_users(include_tokens: bool = False):
    users = await mongodb.get_meta_users()
    if include_tokens:
        return users
    return [_sanitize_meta_user(user) for user in users]


@router.get("/meta-users/{meta_user_id}")
async def get_meta_user(meta_user_id: str, include_tokens: bool = False):
    user = await mongodb.get_meta_user_profile(meta_user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meta user not found"
        )
    accounts = await mongodb.get_accounts_by_meta_user(meta_user_id)
    return {
        "user": user if include_tokens else _sanitize_meta_user(user),
        "connected_accounts": accounts if include_tokens else [_sanitize_account(account) for account in accounts]
    }

@router.post("/accounts")
async def create_account(account: AccountCreate):
    if not account.instagram_business_id.strip() or not account.page_access_token.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="instagram_business_id and page_access_token are required"
        )
    await mongodb.save_page_access_token(
        business_id=account.instagram_business_id.strip(),
        page_access_token=account.page_access_token.strip(),
        account_status="active"
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


# ---------------------------------------------------------------------------
# Meta User Data Deletion Endpoints
# Required by Meta Platform Policy for apps that use Facebook/Instagram Login.
# Register the POST URL in: App Dashboard → App Settings (Basic) →
#   "Data Deletion Callback URL"
# ---------------------------------------------------------------------------

def _parse_signed_request(signed_request: str, app_secret: str) -> Optional[dict]:
    """
    Decode and verify a Meta signed_request.
    Format: base64url(signature).base64url(payload)
    The signature is HMAC-SHA256 of the payload using the app secret.
    Returns the decoded payload dict on success, or None on failure.
    """
    try:
        encoded_sig, payload = signed_request.split(".", 1)

        # Pad base64 strings to a multiple-of-4 length
        def _b64_decode(s: str) -> bytes:
            s += "=" * (-len(s) % 4)
            return base64.urlsafe_b64decode(s)

        sig = _b64_decode(encoded_sig)
        data = json.loads(_b64_decode(payload).decode("utf-8"))

        # Verify HMAC-SHA256
        expected_sig = hmac.new(
            app_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).digest()

        if not hmac.compare_digest(sig, expected_sig):
            logger.warning("Data deletion signed_request: signature mismatch")
            return None

        return data
    except Exception:
        logger.exception("Failed to parse/verify signed_request")
        return None


@router.get("/data-deletion")
async def data_deletion_instructions(request: Request):
    """
    Human-readable Data Deletion Instructions page.
    Register this URL in the Meta App Dashboard as the
    'Data Deletion Instructions URL' if you prefer the manual approach.
    """
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse({
        "title": "User Data Deletion",
        "description": (
            "To request deletion of your data collected through this app, "
            "you may send an email to the app administrator or use the "
            "automated Facebook data deletion flow. Once your request is "
            "received, all stored messages, profile information, and "
            "activity logs associated with your account will be permanently "
            "removed within 30 days."
        ),
        "automated_callback_url": f"{base_url}/api/admin/data-deletion",
        "contact": "admin@example.com"
    })


@router.post("/data-deletion")
async def data_deletion_callback(signed_request: str = Form(...)):
    """
    Meta Data Deletion Callback (POST).
    Meta calls this endpoint when a user requests app data deletion via
    Facebook Settings → Apps and Websites.

    Flow:
      1. Meta POSTs a form-encoded `signed_request` parameter.
      2. We verify the HMAC-SHA256 signature using INSTAGRAM_APP_SECRET.
      3. We extract the `user_id` and delete all associated records.
      4. We return a JSON body with a status `url` and `confirmation_code`
         so Meta can link users to a deletion-status page.
    """
    if not settings.instagram_app_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="App secret is not configured."
        )

    payload = _parse_signed_request(signed_request, settings.instagram_app_secret)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or tampered signed_request."
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="signed_request payload missing user_id."
        )

    # Delete all data for this user
    deleted_counts = await mongodb.delete_user_data(user_id)
    logger.info(f"Data deletion completed for user {user_id}: {deleted_counts}")

    # Generate a unique confirmation code for this request
    confirmation_code = f"DEL-{secrets.token_hex(8).upper()}"

    # Meta requires a publicly reachable status URL; adjust the host as needed
    # (e.g. your ngrok/production domain rather than localhost)
    status_url = f"https://example.com/deletion-status?code={confirmation_code}"

    return JSONResponse({
        "url": status_url,
        "confirmation_code": confirmation_code
    })
