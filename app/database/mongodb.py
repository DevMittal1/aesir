import logging
from datetime import datetime, timezone
from typing import Optional, Union
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

    async def save_page_access_token(
        self,
        business_id: str,
        page_access_token: str,
        page_id: Optional[str] = None,
        page_name: Optional[str] = None,
        meta_user_id: Optional[str] = None,
        instagram_username: Optional[str] = None,
        subscribed_fields: Optional[list[str]] = None,
        subscription_status: Optional[str] = None
    ) -> None:
        """
        Save or update connected Page and Instagram account details.
        """
        if self.db is None:
            return
        try:
            now = datetime.now(timezone.utc)
            update_fields = {
                "page_access_token": page_access_token,
                "updated_at": now
            }
            optional_fields = {
                "page_id": page_id,
                "page_name": page_name,
                "meta_user_id": meta_user_id,
                "instagram_username": instagram_username,
                "subscribed_fields": subscribed_fields,
                "subscription_status": subscription_status
            }
            update_fields.update({
                field: value
                for field, value in optional_fields.items()
                if value is not None
            })

            await self.db.page_access_tokens.update_one(
                {"instagram_business_id": business_id},
                {
                    "$set": update_fields,
                    "$setOnInsert": {"created_at": now}
                },
                upsert=True
            )
            logger.info(f"Successfully saved/updated page access token for business_id {business_id}")
        except Exception:
            logger.exception(f"Failed to save page access token for business_id {business_id}")

    async def save_meta_user_profile(
        self,
        meta_user_id: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
        user_access_token: Optional[str] = None,
        token_expires_in: Optional[int] = None
    ) -> None:
        """
        Save or update the Meta user who completed the OAuth flow.
        """
        if self.db is None:
            return
        try:
            now = datetime.now(timezone.utc)
            update_fields = {
                "updated_at": now
            }
            optional_fields = {
                "name": name,
                "email": email,
                "user_access_token": user_access_token,
                "token_expires_in": token_expires_in
            }
            update_fields.update({
                field: value
                for field, value in optional_fields.items()
                if value is not None
            })

            await self.db.meta_users.update_one(
                {"meta_user_id": meta_user_id},
                {
                    "$set": update_fields,
                    "$setOnInsert": {"created_at": now}
                },
                upsert=True
            )
            logger.info(f"Successfully saved/updated Meta user profile {meta_user_id}")
        except Exception:
            logger.exception(f"Failed to save Meta user profile {meta_user_id}")

    async def get_instagram_user(self, user_id: str) -> Optional[dict]:
        """
        Retrieve an Instagram User profile document from the database.
        """
        if self.db is None:
            return None
        try:
            return await self.db.instagram_users.find_one({"instagram_user_id": user_id})
        except Exception:
            logger.exception(f"Failed to retrieve user {user_id}")
            return None

    async def upsert_instagram_user(self, business_id: str, user_id: str, profile_data: Optional[dict] = None) -> None:
        """
        Upsert an Instagram User profile in the database, updating last_seen_at.
        """
        if self.db is None:
            return
        try:
            now = datetime.now(timezone.utc)
            update_fields = {
                "last_seen_at": now,
                "instagram_business_id": business_id
            }
            if profile_data:
                if "name" in profile_data:
                    update_fields["name"] = profile_data["name"]
                if "profile_pic" in profile_data:
                    update_fields["profile_pic"] = profile_data["profile_pic"]

            await self.db.instagram_users.update_one(
                {"instagram_user_id": user_id},
                {
                    "$set": update_fields,
                    "$setOnInsert": {
                        "first_seen_at": now
                    }
                },
                upsert=True
            )
            logger.info(f"Successfully upserted user {user_id}")
        except Exception:
            logger.exception(f"Failed to upsert user {user_id}")

    async def log_user_activity(self, business_id: str, user_id: str, activity_type: str, timestamp: Union[int, datetime], details: dict) -> None:
        """
        Log an Instagram User activity/event in the database.
        """
        if self.db is None:
            return
        try:
            if isinstance(timestamp, (int, float)):
                if timestamp > 1e11:  # Milliseconds
                    dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                else:  # Seconds
                    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            elif isinstance(timestamp, datetime):
                dt = timestamp
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.now(timezone.utc)

            activity_doc = {
                "instagram_user_id": user_id,
                "instagram_business_id": business_id,
                "activity_type": activity_type,
                "timestamp": dt,
                "details": details,
                "logged_at": datetime.now(timezone.utc)
            }
            await self.db.user_activities.insert_one(activity_doc)
            logger.info(f"Logged activity '{activity_type}' for user {user_id}")
        except Exception:
            logger.exception(f"Failed to log activity for user {user_id}")

    async def get_all_page_access_tokens(self) -> list:
        """
        Retrieve all page access token documents.
        """
        if self.db is None:
            return []
        try:
            cursor = self.db.page_access_tokens.find()
            res = await cursor.to_list(length=None)
            for doc in res:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            return res
        except Exception:
            logger.exception("Failed to retrieve all page access tokens.")
            return []

    async def delete_page_access_token(self, business_id: str) -> bool:
        """
        Delete a page access token document by instagram_business_id.
        """
        if self.db is None:
            return False
        try:
            result = await self.db.page_access_tokens.delete_one({"instagram_business_id": business_id})
            return result.deleted_count > 0
        except Exception:
            logger.exception(f"Failed to delete page access token for business_id {business_id}.")
            return False

    async def get_instagram_users(self) -> list:
        """
        Retrieve all tracked Instagram Users sorted by last seen activity.
        """
        if self.db is None:
            return []
        try:
            cursor = self.db.instagram_users.find().sort("last_seen_at", -1)
            res = await cursor.to_list(length=None)
            for doc in res:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            return res
        except Exception:
            logger.exception("Failed to retrieve instagram users.")
            return []

    async def save_chat_message(self, direction: str, sender_id: str, recipient_id: str, text: Optional[str] = None, msg_type: str = "text", timestamp: Optional[datetime] = None, metadata: Optional[dict] = None) -> None:
        """
        Save a chat message (incoming or outgoing) to build a unified chat history.
        """
        if self.db is None:
            return
        try:
            dt = timestamp or datetime.now(timezone.utc)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            doc = {
                "direction": direction,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "text": text,
                "msg_type": msg_type,
                "timestamp": dt,
                "metadata": metadata or {}
            }
            await self.db.chat_history.insert_one(doc)
            logger.info(f"Saved {direction} chat message for sender_id={sender_id}")
        except Exception:
            logger.exception("Failed to save chat message.")

    async def get_chat_history(self, user_id: str) -> list:
        """
        Retrieve chronological message history with a specific user.
        """
        if self.db is None:
            return []
        try:
            cursor = self.db.chat_history.find({
                "$or": [
                    {"sender_id": user_id},
                    {"recipient_id": user_id}
                ]
            }).sort("timestamp", 1)
            res = await cursor.to_list(length=None)
            for doc in res:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            return res
        except Exception:
            logger.exception(f"Failed to retrieve chat history for user {user_id}.")
            return []

    async def get_recent_payloads(self, limit: int = 50) -> list:
        """
        Retrieve recent webhook raw payloads for log monitoring.
        """
        if self.db is None:
            return []
        try:
            cursor = self.db.webhook_payloads.find().sort("received_at", -1).limit(limit)
            res = await cursor.to_list(length=None)
            for doc in res:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            return res
        except Exception:
            logger.exception("Failed to retrieve recent webhook payloads.")
            return []

    async def get_dashboard_stats(self) -> dict:
        """
        Get dashboard statistics counts.
        """
        if self.db is None:
            return {"total_payloads": 0, "failed_payloads": 0, "total_users": 0, "total_messages": 0}
        try:
            total_payloads = await self.db.webhook_payloads.count_documents({})
            failed_payloads = await self.db.webhook_payloads.count_documents({"status": "failed"})
            total_users = await self.db.instagram_users.count_documents({})
            total_messages = await self.db.chat_history.count_documents({})
            return {
                "total_payloads": total_payloads,
                "failed_payloads": failed_payloads,
                "total_users": total_users,
                "total_messages": total_messages
            }
        except Exception:
            logger.exception("Failed to get dashboard stats.")
            return {"total_payloads": 0, "failed_payloads": 0, "total_users": 0, "total_messages": 0}

    async def delete_user_data(self, user_id: str) -> dict:
        """
        Delete all stored data for a given Instagram/Facebook user_id.
        Covers: instagram_users, chat_history, user_activities, processed_events.
        Returns a dict with deleted_counts per collection.
        """
        if self.db is None:
            logger.warning("MongoDB not connected. Cannot delete user data.")
            return {}
        counts = {}
        try:
            r = await self.db.instagram_users.delete_many({"instagram_user_id": user_id})
            counts["instagram_users"] = r.deleted_count

            r = await self.db.chat_history.delete_many({
                "$or": [{"sender_id": user_id}, {"recipient_id": user_id}]
            })
            counts["chat_history"] = r.deleted_count

            r = await self.db.user_activities.delete_many({"instagram_user_id": user_id})
            counts["user_activities"] = r.deleted_count

            logger.info(f"Deleted all data for user {user_id}: {counts}")
        except Exception:
            logger.exception(f"Failed to delete data for user {user_id}")
        return counts

# Database singleton
mongodb = MongoDB()
