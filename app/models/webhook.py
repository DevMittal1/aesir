from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# --- User Identity Models ---
class UserID(BaseModel):
    id: str

# --- Attachment Models (Images, Videos, Audios, Files, Story Mentions) ---
class Attachment(BaseModel):
    type: str  # 'image', 'video', 'audio', 'file', 'story_mention', 'fallback'
    payload: Optional[Dict[str, Any]] = None

# --- Message Details ---
class QuickReply(BaseModel):
    payload: str

class ReplyTo(BaseModel):
    mid: str

class ReferralEvent(BaseModel):
    ref: str
    source: Optional[str] = None
    type: Optional[str] = None
    ad_id: Optional[str] = None

class MessageContent(BaseModel):
    mid: str
    text: Optional[str] = None
    attachments: Optional[List[Attachment]] = None
    quick_reply: Optional[QuickReply] = None
    reply_to: Optional[ReplyTo] = None
    referral: Optional[ReferralEvent] = None
    is_echo: Optional[bool] = False
    metadata: Optional[str] = None

# --- Postback details (buttons, Get Started trigger) ---
class PostbackContent(BaseModel):
    title: str
    payload: str
    referral: Optional[ReferralEvent] = None

class ReadEvent(BaseModel):
    mid: Optional[str] = None
    watermark: Optional[int] = None

class ReactionEvent(BaseModel):
    mid: str
    action: str  # 'react' or 'unreact'
    reaction: Optional[str] = None
    emoji: Optional[str] = None

class OptinEvent(BaseModel):
    ref: Optional[str] = None
    user_ref: Optional[str] = None
    type: Optional[str] = None
    payload: Optional[str] = None

# --- Main Event Wrapper ---
class MessagingEvent(BaseModel):
    sender: UserID
    recipient: UserID
    timestamp: int
    message: Optional[MessageContent] = None
    postback: Optional[PostbackContent] = None
    referral: Optional[ReferralEvent] = None
    read: Optional[ReadEvent] = None
    reaction: Optional[ReactionEvent] = None
    optin: Optional[OptinEvent] = None

# --- Instagram Graph API Changes (Comments, Story Mentions, Media) ---
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
