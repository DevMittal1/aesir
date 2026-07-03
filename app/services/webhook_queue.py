import logging
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Optional
from app.database.mongodb import mongodb
from app.models.webhook import InstagramWebhookPayload, MessagingEvent, WebhookChange
from app.services.instagram import instagram_service

logger = logging.getLogger(__name__)

class WebhookQueue:
    def __init__(self):
        self._queue = asyncio.Queue()
        self._worker_task = None
        self._running = False

    async def start(self) -> None:
        """
        Start the background worker queue.
        Also recovers any pending/processing payloads from MongoDB.
        """
        if self._running:
            return
        self._running = True

        # Recovery on startup: find any received/processing payloads in MongoDB
        # and enqueue them to be processed.
        try:
            pending = await mongodb.get_pending_payloads()
            if pending:
                logger.info(f"Found {len(pending)} pending/interrupted webhook payloads. Enqueuing for processing.")
                for doc in pending:
                    payload_id = str(doc["_id"])
                    await self._queue.put((payload_id, doc["payload"]))
        except Exception:
            logger.exception("Failed to recover pending webhook payloads from database during startup.")

        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Webhook background queue worker started.")

    async def stop(self) -> None:
        """
        Gracefully stop the background worker queue.
        """
        if not self._running:
            return
        self._running = False
        logger.info("Stopping webhook background queue worker...")
        if self._worker_task:
            self._worker_task.cancel()
            await asyncio.wait([self._worker_task])
            self._worker_task = None
        logger.info("Webhook background queue worker stopped.")

    async def enqueue(self, payload_id: str, payload_dict: dict) -> None:
        """
        Enqueue a webhook payload for asynchronous processing.
        """
        await self._queue.put((payload_id, payload_dict))

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                payload_id, payload_dict = await self._queue.get()
                try:
                    await self._process_payload(payload_id, payload_dict)
                except Exception:
                    logger.exception(f"Error processing webhook payload {payload_id}")
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in webhook queue worker loop")
                await asyncio.sleep(1)

    async def _process_payload(self, payload_id: str, payload_dict: dict) -> None:
        """
        Process the webhook payload, applying idempotency checks.
        """
        logger.info(f"Worker processing payload ID: {payload_id}")
        await mongodb.update_payload_status(payload_id, "processing")

        try:
            payload = InstagramWebhookPayload.model_validate(payload_dict)
            if payload.object != "instagram":
                logger.warning(f"Unsupported webhook object type: {payload.object}")
                await mongodb.update_payload_status(payload_id, "processed")
                return

            for entry in payload.entry:
                if entry.messaging:
                    for event in entry.messaging:
                        await self._process_messaging_event(entry.id, event)

                if entry.changes:
                    for change in entry.changes:
                        await self._process_change_event(change)

            await mongodb.update_payload_status(payload_id, "processed")
            logger.info(f"Worker successfully finished processing payload ID: {payload_id}")

        except Exception as e:
            logger.exception(f"Failed to process webhook payload {payload_id}")
            await mongodb.update_payload_status(payload_id, "failed", error=str(e))

    async def _process_messaging_event(self, business_id: str, event: MessagingEvent) -> None:
        sender_id = event.sender.id
        
        access_token = await mongodb.get_page_access_token(business_id)
        if not access_token:
            logger.info(f"No custom Page Access Token found for business_id {business_id}. Falling back to default/mock token.")
        
        await self._track_user(business_id, sender_id, access_token)

        if event.message:
            await self._handle_message_event(sender_id, event, access_token)
        elif event.postback:
            await self._handle_postback_event(sender_id, event, access_token)
        elif event.read:
            await self._handle_read_event(sender_id, event, access_token)
        elif event.reaction:
            await self._handle_reaction_event(sender_id, event, access_token)
        elif event.referral:
            await self._handle_referral_event(sender_id, event, access_token)
        elif event.optin:
            await self._handle_optin_event(sender_id, event, access_token)
        else:
            logger.info(f"Received unhandled messaging event type from {sender_id}: {event}")

    async def _track_user(self, business_id: str, sender_id: str, access_token: Optional[str]) -> None:
        try:
            should_fetch = await self._should_fetch_profile(sender_id)
            profile_data = None
            if should_fetch:
                profile_data = await instagram_service.get_user_profile(sender_id, access_token)
            await mongodb.upsert_instagram_user(business_id, sender_id, profile_data)
        except Exception:
            logger.exception(f"Failed to track user profile for sender {sender_id}")

    async def _should_fetch_profile(self, sender_id: str) -> bool:
        user = await mongodb.get_instagram_user(sender_id)
        if not user:
            return True
        last_updated = user.get("updated_at") or user.get("last_seen_at")
        if not last_updated:
            return True
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last_updated).total_seconds() >= 86400

    async def _handle_message_event(self, sender_id: str, event: MessagingEvent, access_token: Optional[str]) -> None:
        mid = event.message.mid
        if not mid:
            logger.warning(f"Received message event without mid from sender: {sender_id}")
            return

        # Idempotency check
        if await mongodb.is_event_processed(mid):
            logger.info(f"Duplicate message event ignored. mid={mid}")
            return

        await mongodb.log_user_activity(
            event.recipient.id,
            sender_id,
            "message",
            event.timestamp,
            event.message.model_dump(exclude_none=True)
        )

        await instagram_service.handle_message_event(
            sender_id, event.message.model_dump(exclude_none=True), access_token=access_token
        )
        await mongodb.mark_event_processed(mid)

    async def _handle_postback_event(self, sender_id: str, event: MessagingEvent, access_token: Optional[str]) -> None:
        # Generate a unique key for postback based on sender, recipient, timestamp, and payload
        raw_key = f"postback_{sender_id}_{event.recipient.id}_{event.timestamp}_{event.postback.payload}"
        postback_id = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        # Idempotency check
        if await mongodb.is_event_processed(postback_id):
            logger.info(f"Duplicate postback event ignored. postback_id={postback_id}")
            return

        await mongodb.log_user_activity(
            event.recipient.id,
            sender_id,
            "postback",
            event.timestamp,
            event.postback.model_dump(exclude_none=True)
        )

        await instagram_service.handle_postback_event(
            sender_id, event.postback.model_dump(exclude_none=True), access_token=access_token
        )
        await mongodb.mark_event_processed(postback_id)

    async def _handle_read_event(self, sender_id: str, event: MessagingEvent, access_token: Optional[str]) -> None:
        # Generate a unique key for read events
        watermark = event.read.watermark or event.timestamp
        read_id = f"read_{sender_id}_{event.recipient.id}_{watermark}"
        
        if await mongodb.is_event_processed(read_id):
            logger.info(f"Duplicate read event ignored. read_id={read_id}")
            return

        await mongodb.log_user_activity(
            event.recipient.id,
            sender_id,
            "read",
            event.timestamp,
            event.read.model_dump(exclude_none=True)
        )
            
        await instagram_service.handle_read_event(
            sender_id, event.read.model_dump(exclude_none=True), access_token=access_token
        )
        await mongodb.mark_event_processed(read_id)

    async def _handle_reaction_event(self, sender_id: str, event: MessagingEvent, access_token: Optional[str]) -> None:
        # Generate a unique key for reaction events
        raw_key = f"reaction_{sender_id}_{event.recipient.id}_{event.reaction.mid}_{event.reaction.action}"
        reaction_id = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        
        if await mongodb.is_event_processed(reaction_id):
            logger.info(f"Duplicate reaction event ignored. reaction_id={reaction_id}")
            return

        await mongodb.log_user_activity(
            event.recipient.id,
            sender_id,
            "reaction",
            event.timestamp,
            event.reaction.model_dump(exclude_none=True)
        )
            
        await instagram_service.handle_reaction_event(
            sender_id, event.reaction.model_dump(exclude_none=True), access_token=access_token
        )
        await mongodb.mark_event_processed(reaction_id)

    async def _handle_referral_event(self, sender_id: str, event: MessagingEvent, access_token: Optional[str]) -> None:
        # Generate a unique key for referral events
        raw_key = f"referral_{sender_id}_{event.recipient.id}_{event.timestamp}_{event.referral.ref}"
        referral_id = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        
        if await mongodb.is_event_processed(referral_id):
            logger.info(f"Duplicate referral event ignored. referral_id={referral_id}")
            return

        await mongodb.log_user_activity(
            event.recipient.id,
            sender_id,
            "referral",
            event.timestamp,
            event.referral.model_dump(exclude_none=True)
        )
            
        await instagram_service.handle_referral_event(
            sender_id, event.referral.model_dump(exclude_none=True), access_token=access_token
        )
        await mongodb.mark_event_processed(referral_id)

    async def _handle_optin_event(self, sender_id: str, event: MessagingEvent, access_token: Optional[str]) -> None:
        # Generate a unique key for optin events
        optin_ref = event.optin.ref or "default_ref"
        raw_key = f"optin_{sender_id}_{event.recipient.id}_{event.timestamp}_{optin_ref}"
        optin_id = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        
        if await mongodb.is_event_processed(optin_id):
            logger.info(f"Duplicate optin event ignored. optin_id={optin_id}")
            return

        await mongodb.log_user_activity(
            event.recipient.id,
            sender_id,
            "optin",
            event.timestamp,
            event.optin.model_dump(exclude_none=True)
        )
            
        await instagram_service.handle_optin_event(
            sender_id, event.optin.model_dump(exclude_none=True), access_token=access_token
        )
        await mongodb.mark_event_processed(optin_id)

    async def _process_change_event(self, change: WebhookChange) -> None:
        # Determine unique event ID for the change
        val = change.value
        change_id = None
        
        if isinstance(val, dict):
            change_id = val.get("comment_id") or val.get("id") or val.get("media_id")
            if not change_id:
                # Generate unique key from dict structure
                raw_str = f"{change.field}_{str(sorted(val.items()))}"
                change_id = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
        else:
            raw_str = f"{change.field}_{str(val)}"
            change_id = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

        # Idempotency check
        if await mongodb.is_event_processed(change_id):
            logger.info(f"Duplicate change event ignored. change_id={change_id}")
            return

        logger.info(f"Received change notification field='{change.field}', value={change.value}")
        
        # If there were business logic for changes, we'd invoke it here.
        # Since it only logs, we mark it processed.
        await mongodb.mark_event_processed(change_id)

webhook_queue = WebhookQueue()
