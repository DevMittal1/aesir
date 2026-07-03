import logging
from datetime import datetime, timezone
from typing import Optional
from pymongo import AsyncMongoClient
from app.config import settings

logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        self.client: Optional[AsyncMongoClient] = None
        self.db = None

    async def connect(self) -> None:
        """
        Connect to MongoDB.
        """
        if self.client is not None:
            return
            
        logger.info(f"Connecting to MongoDB at {settings.mongodb_uri}...")
        try:
            self.client = AsyncMongoClient(settings.mongodb_uri)
            self.db = self.client[settings.mongodb_db_name]
            # Verify connection
            await self.client.admin.command('ping')
            # Create unique index on processed_events
            await self.db.processed_events.create_index("event_id", unique=True)
            logger.info("Successfully connected to MongoDB.")
        except Exception:
            logger.exception("Failed to connect to MongoDB.")
            raise

    async def close(self) -> None:
        """
        Close MongoDB connection.
        """
        if self.client is None:
            return
            
        logger.info("Closing MongoDB connection...")
        await self.client.close()
        self.client = None
        self.db = None
        logger.info("MongoDB connection closed.")

    async def save_webhook_payload(self, payload: dict, client_ip: str) -> Optional[str]:
        """
        Save the raw webhook payload to MongoDB.
        """
        if self.db is None:
            logger.warning("MongoDB is not connected. Skipping webhook payload storage.")
            return None
            
        document = {
            "received_at": datetime.now(timezone.utc),
            "client_ip": client_ip,
            "payload": payload,
            "status": "received"
        }
        
        try:
            result = await self.db.webhook_payloads.insert_one(document)
            logger.info(f"Saved webhook payload to MongoDB with ID: {result.inserted_id}")
            return str(result.inserted_id)
        except Exception:
            logger.exception("Failed to save webhook payload to MongoDB.")
            return None

    async def get_pending_payloads(self) -> list:
        """
        Retrieve all webhook payloads that are pending or were in progress but interrupted.
        """
        if self.db is None:
            return []
        try:
            cursor = self.db.webhook_payloads.find(
                {"status": {"$in": ["received", "processing"]}}
            )
            return await cursor.to_list(length=None)
        except Exception:
            logger.exception("Failed to retrieve pending webhook payloads.")
            return []

    async def update_payload_status(self, payload_id: str, status: str, error: Optional[str] = None) -> None:
        """
        Update the status of a saved webhook payload.
        """
        if self.db is None:
            return
        from bson import ObjectId
        update_doc = {
            "$set": {
                "status": status,
                "updated_at": datetime.now(timezone.utc)
            }
        }
        if error:
            update_doc["$set"]["error"] = error
        try:
            await self.db.webhook_payloads.update_one(
                {"_id": ObjectId(payload_id)},
                update_doc
            )
        except Exception:
            logger.exception(f"Failed to update payload status for {payload_id}.")

    async def is_event_processed(self, event_id: str) -> bool:
        """
        Check if a specific sub-event (message, postback, change) has already been processed.
        """
        if self.db is None:
            return False
        try:
            doc = await self.db.processed_events.find_one({"event_id": event_id})
            return doc is not None
        except Exception:
            logger.exception(f"Failed to check if event {event_id} is processed.")
            return False

    async def mark_event_processed(self, event_id: str) -> None:
        """
        Mark a specific sub-event as processed.
        """
        if self.db is None:
            return
        try:
            await self.db.processed_events.insert_one({
                "event_id": event_id,
                "processed_at": datetime.now(timezone.utc)
            })
        except Exception:
            logger.exception(f"Failed to mark event {event_id} as processed.")

    async def get_page_access_token(self, business_id: str) -> Optional[str]:
        """
        Retrieve the Page Access Token for a given Instagram Business Account ID.
        """
        if self.db is None:
            return None
        try:
            doc = await self.db.page_access_tokens.find_one({"instagram_business_id": business_id})
            if doc:
                return doc.get("page_access_token")
            return None
        except Exception:
            logger.exception(f"Failed to retrieve page access token for business_id {business_id}")
            return None

    async def save_page_access_token(self, business_id: str, page_access_token: str) -> None:
        """
        Save or update a Page Access Token for an Instagram Business Account ID.
        """
        if self.db is None:
            return
        try:
            await self.db.page_access_tokens.update_one(
                {"instagram_business_id": business_id},
                {"$set": {
                    "page_access_token": page_access_token,
                    "updated_at": datetime.now(timezone.utc)
                }},
                upsert=True
            )
            logger.info(f"Successfully saved/updated page access token for business_id {business_id}")
        except Exception:
            logger.exception(f"Failed to save page access token for business_id {business_id}")

# Database singleton
mongodb = MongoDB()
