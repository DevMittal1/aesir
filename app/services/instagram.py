import logging
import httpx
from typing import Dict, Any, List, Optional
from app.config import settings

logger = logging.getLogger(__name__)

class InstagramService:
    def __init__(self):
        self.api_version = settings.instagram_api_version
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    async def send_raw_message(self, payload: Dict[str, Any], access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Send a raw messaging payload to the Meta Graph API.
        """
        if not access_token:
            logger.warning("Attempted to send message without a page access token.")
            raise ValueError("access_token is required for sending messages in SaaS multi-tenant mode.")
            
        url = f"{self.base_url}/me/messages"
        params = {"access_token": access_token}
        
        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Sending message payload to {url}: {payload}")
                if access_token in ("mock_page_access_token", "mock_saas_page_access_token"):
                    logger.info("Mock Page Access Token detected. Skipping network call.")
                    return {"recipient_id": payload.get("recipient", {}).get("id"), "message_id": "mock_mid_12345"}
                
                response = await client.post(url, json=payload, params=params, timeout=10.0)
                response.raise_for_status()
                res_data = response.json()
                logger.info(f"Meta Graph API response: {res_data}")
                return res_data
            except httpx.HTTPStatusError as exc:
                logger.exception("HTTP error occurred while calling Meta")
                raise exc
            except Exception as exc:
                logger.exception("Error occurred while sending message to Meta")
                raise exc

    async def send_text_message(self, recipient_id: str, text: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Send a standard text message.
        """
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text}
        }
        return await self.send_raw_message(payload, access_token=access_token)

    async def send_image_message(self, recipient_id: str, image_url: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Send an image attachment.
        """
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {
                        "url": image_url,
                        "is_reusable": True
                    }
                }
            }
        }
        return await self.send_raw_message(payload, access_token=access_token)

    async def send_quick_replies(self, recipient_id: str, text: str, replies: List[Dict[str, str]], access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Send text with quick reply buttons.
        """
        quick_replies = [
            {
                "content_type": "text",
                "title": r["title"],
                "payload": r["payload"]
            }
            for r in replies
        ]
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "text": text,
                "quick_replies": quick_replies
            }
        }
        return await self.send_raw_message(payload, access_token=access_token)

    async def _handle_text_message(self, sender_id: str, text: str, access_token: Optional[str] = None) -> None:
        text_lower = text.lower().strip()
        if text_lower == "image":
            await self.send_image_message(
                sender_id,
                "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=500",
                access_token=access_token
            )
        elif text_lower == "help":
            await self.send_quick_replies(
                sender_id,
                "Here is how I can help you:",
                [
                    {"title": "Get Started", "payload": "PAYLOAD_START"},
                    {"title": "View Services", "payload": "PAYLOAD_SERVICES"}
                ],
                access_token=access_token
            )
        else:
            await self.send_text_message(
                sender_id,
                f"Echoing back your message: '{text}'",
                access_token=access_token
            )

    async def _handle_attachments(self, sender_id: str, attachments: List[Dict[str, Any]], access_token: Optional[str] = None) -> None:
        for attachment in attachments:
            att_type = attachment.get("type")
            att_payload = attachment.get("payload", {})
            att_url = att_payload.get("url") if att_payload else None
            
            if att_type == "story_mention":
                await self.send_text_message(
                    sender_id,
                    "Thanks for mentioning us in your Story! 📸",
                    access_token=access_token
                )
            else:
                await self.send_text_message(
                    sender_id,
                    f"Received your attachment of type: {att_type} at {att_url}",
                    access_token=access_token
                )

    async def handle_message_event(self, sender_id: str, message: Dict[str, Any], access_token: Optional[str] = None) -> None:
        """
        Handle a received message event.
        """
        is_echo = message.get("is_echo", False)
        if is_echo:
            logger.info(f"Skipping echo message for sender {sender_id}")
            return

        text = message.get("text")
        attachments = message.get("attachments")
        quick_reply = message.get("quick_reply")

        logger.info(f"Received message from user {sender_id}: text={text}, attachments={attachments}, quick_reply={quick_reply}")

        if quick_reply:
            qr_payload = quick_reply.get("payload")
            await self.send_text_message(
                sender_id, 
                f"You selected option with payload: {qr_payload}",
                access_token=access_token
            )
        elif text:
            await self._handle_text_message(sender_id, text, access_token=access_token)
        elif attachments:
            await self._handle_attachments(sender_id, attachments, access_token=access_token)

    async def handle_postback_event(self, sender_id: str, postback: Dict[str, Any], access_token: Optional[str] = None) -> None:
        """
        Handle postback events.
        """
        title = postback.get("title")
        payload = postback.get("payload")
        logger.info(f"Received postback from user {sender_id}: title='{title}', payload='{payload}'")
        
        await self.send_text_message(
            sender_id,
            f"Received button click: '{title}' (payload: {payload})",
            access_token=access_token
        )

    async def handle_read_event(self, sender_id: str, read: Dict[str, Any], access_token: Optional[str] = None) -> None:
        """
        Handle read receipt events.
        """
        watermark = read.get("watermark")
        mid = read.get("mid")
        logger.info(f"Received read receipt from user {sender_id}: watermark={watermark}, mid={mid}")

    async def handle_reaction_event(self, sender_id: str, reaction: Dict[str, Any], access_token: Optional[str] = None) -> None:
        """
        Handle message reaction events.
        """
        mid = reaction.get("mid")
        action = reaction.get("action")
        emoji = reaction.get("emoji")
        logger.info(f"Received reaction from user {sender_id}: mid={mid}, action={action}, emoji={emoji}")
        
        # Acknowledge the reaction if it's "react"
        if action == "react":
            await self.send_text_message(
                sender_id,
                f"Glad you liked that message! ❤️",
                access_token=access_token
            )

    async def handle_referral_event(self, sender_id: str, referral: Dict[str, Any], access_token: Optional[str] = None) -> None:
        """
        Handle referral events.
        """
        ref = referral.get("ref")
        source = referral.get("source")
        ref_type = referral.get("type")
        logger.info(f"Received referral event from user {sender_id}: ref={ref}, source={source}, type={ref_type}")
        
        await self.send_text_message(
            sender_id,
            f"Welcome! Thanks for joining us via the link (referral code: {ref}). How can we help you today?",
            access_token=access_token
        )

    async def handle_optin_event(self, sender_id: str, optin: Dict[str, Any], access_token: Optional[str] = None) -> None:
        """
        Handle opt-in events.
        """
        ref = optin.get("ref")
        user_ref = optin.get("user_ref")
        logger.info(f"Received opt-in event from user {sender_id}: ref={ref}, user_ref={user_ref}")
        
        await self.send_text_message(
            sender_id,
            f"Thank you for opting in! (Ref: {ref})",
            access_token=access_token
        )

instagram_service = InstagramService()
