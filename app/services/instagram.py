import logging
import httpx
from typing import Dict, Any, List, Optional
from app.config import settings

logger = logging.getLogger(__name__)

class InstagramService:
    def __init__(self):
        self.api_version = settings.instagram_api_version
        self.page_access_token = settings.instagram_page_access_token
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    async def send_raw_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a raw messaging payload to the Meta Graph API.
        """
        url = f"{self.base_url}/me/messages"
        params = {"access_token": self.page_access_token}
        
        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Sending message payload to {url}: {payload}")
                if self.page_access_token == "mock_page_access_token":
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

    async def send_text_message(self, recipient_id: str, text: str) -> Dict[str, Any]:
        """
        Send a standard text message.
        """
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": text}
        }
        return await self.send_raw_message(payload)

    async def send_image_message(self, recipient_id: str, image_url: str) -> Dict[str, Any]:
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
        return await self.send_raw_message(payload)

    async def send_quick_replies(self, recipient_id: str, text: str, replies: List[Dict[str, str]]) -> Dict[str, Any]:
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
        return await self.send_raw_message(payload)

    async def _handle_text_message(self, sender_id: str, text: str) -> None:
        text_lower = text.lower().strip()
        if text_lower == "image":
            await self.send_image_message(
                sender_id,
                "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=500"
            )
        elif text_lower == "help":
            await self.send_quick_replies(
                sender_id,
                "Here is how I can help you:",
                [
                    {"title": "Get Started", "payload": "PAYLOAD_START"},
                    {"title": "View Services", "payload": "PAYLOAD_SERVICES"}
                ]
            )
        else:
            await self.send_text_message(
                sender_id,
                f"Echoing back your message: '{text}'"
            )

    async def _handle_attachments(self, sender_id: str, attachments: List[Dict[str, Any]]) -> None:
        for attachment in attachments:
            att_type = attachment.get("type")
            att_payload = attachment.get("payload", {})
            att_url = att_payload.get("url") if att_payload else None
            
            if att_type == "story_mention":
                await self.send_text_message(
                    sender_id,
                    "Thanks for mentioning us in your Story! 📸"
                )
            else:
                await self.send_text_message(
                    sender_id,
                    f"Received your attachment of type: {att_type} at {att_url}"
                )

    async def handle_message_event(self, sender_id: str, message: Dict[str, Any]) -> None:
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
                f"You selected option with payload: {qr_payload}"
            )
        elif text:
            await self._handle_text_message(sender_id, text)
        elif attachments:
            await self._handle_attachments(sender_id, attachments)

    async def handle_postback_event(self, sender_id: str, postback: Dict[str, Any]) -> None:
        """
        Handle postback events.
        """
        title = postback.get("title")
        payload = postback.get("payload")
        logger.info(f"Received postback from user {sender_id}: title='{title}', payload='{payload}'")
        
        await self.send_text_message(
            sender_id,
            f"Received button click: '{title}' (payload: {payload})"
        )

instagram_service = InstagramService()
