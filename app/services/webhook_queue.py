import logging
import asyncio
import hashlib
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
                        await self._process_messaging_event(event)

                if entry.changes:
                    for change in entry.changes:
                        await self._process_change_event(change)

            await mongodb.update_payload_status(payload_id, "processed")
            logger.info(f"Worker successfully finished processing payload ID: {payload_id}")

        except Exception as e:
            logger.exception(f"Failed to process webhook payload {payload_id}")
            await mongodb.update_payload_status(payload_id, "failed", error=str(e))

    async def _process_messaging_event(self, event: MessagingEvent) -> None:
        sender_id = event.sender.id
        
        if event.message:
            mid = event.message.mid
            if not mid:
                logger.warning(f"Received message event without mid from sender: {sender_id}")
                return

            # Idempotency check
            if await mongodb.is_event_processed(mid):
                logger.info(f"Duplicate message event ignored. mid={mid}")
                return

            await instagram_service.handle_message_event(
                sender_id, event.message.model_dump(exclude_none=True)
            )
            await mongodb.mark_event_processed(mid)

        elif event.postback:
            # Generate a unique key for postback based on sender, recipient, timestamp, and payload
            raw_key = f"postback_{sender_id}_{event.recipient.id}_{event.timestamp}_{event.postback.payload}"
            postback_id = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

            # Idempotency check
            if await mongodb.is_event_processed(postback_id):
                logger.info(f"Duplicate postback event ignored. postback_id={postback_id}")
                return

            await instagram_service.handle_postback_event(
                sender_id, event.postback.model_dump(exclude_none=True)
            )
            await mongodb.mark_event_processed(postback_id)

        else:
            logger.info(f"Received unhandled messaging event type from {sender_id}: {event}")

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
