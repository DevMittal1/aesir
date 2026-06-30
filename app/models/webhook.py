from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# --- User Identity Models ---
class UserID(BaseModel):
    id: str

# --- Attachment Models (Images, Videos, Audios, Files, Story Mentions) ---
class AttachmentPayload(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    sticker_id: Optional[int] = None

class Attachment(BaseModel):
    type: str  # 'image', 'video', 'audio', 'file', 'story_mention', 'fallback'
    payload: Optional[AttachmentPayload] = None

# --- Message Details ---
class QuickReply(BaseModel):
    payload: str

class ReplyTo(BaseModel):
    mid: str

class MessageContent(BaseModel):
    mid: str
    text: Optional[str] = None
    attachments: Optional[List[Attachment]] = None
    quick_reply: Optional[QuickReply] = None
    reply_to: Optional[ReplyTo] = None
    is_echo: Optional[bool] = False
    app_id: Optional[int] = None
    metadata: Optional[str] = None

# --- Postback details (buttons, Get Started trigger) ---
class PostbackContent(BaseModel):
    title: str
    payload: str
    referral: Optional[Dict[str, Any]] = None

# --- Main Event Wrapper ---
class MessagingEvent(BaseModel):
    sender: UserID
    recipient: UserID
    timestamp: int
    message: Optional[MessageContent] = None
    postback: Optional[PostbackContent] = None
    referral: Optional[Dict[str, Any]] = None
    read: Optional[Dict[str, Any]] = None
    delivery: Optional[Dict[str, Any]] = None

# --- Instagram Graph API Changes (Comments, Story Mentions, Media) ---
class ChangeValue(BaseModel):
    media_id: Optional[str] = None
    comment_id: Optional[str] = None
    text: Optional[str] = None
    from_user: Optional[Dict[str, Any]] = Field(None, alias="from")
    id: Optional[str] = None
    username: Optional[str] = None

class WebhookChange(BaseModel):
    field: str
    value: Dict[str, Any]

# --- Webhook Entry ---
class WebhookEntry(BaseModel):
    id: str
    time: int
    messaging: Optional[List[MessagingEvent]] = None
    changes: Optional[List[WebhookChange]] = None

# --- Root Payload ---
class InstagramWebhookPayload(BaseModel):
    object: str
    entry: List[WebhookEntry]
