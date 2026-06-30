import logging
from datetime import datetime
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None

    async def connect(self) -> None:
        """
        Connect to MongoDB.
        """
        if self.client is not None:
            return
            
        logger.info(f"Connecting to MongoDB at {settings.mongodb_uri}...")
        try:
            self.client = AsyncIOMotorClient(settings.mongodb_uri)
            self.db = self.client[settings.mongodb_db_name]
            # Verify connection
            await self.client.admin.command('ping')
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
        self.client.close()
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
            "received_at": datetime.utcnow(),
            "client_ip": client_ip,
            "payload": payload
        }
        
        try:
            result = await self.db.webhook_payloads.insert_one(document)
            logger.info(f"Saved webhook payload to MongoDB with ID: {result.inserted_id}")
            return str(result.inserted_id)
        except Exception:
            logger.exception("Failed to save webhook payload to MongoDB.")
            return None

# Database singleton
mongodb = MongoDB()
