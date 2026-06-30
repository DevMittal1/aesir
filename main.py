import logging
import uvicorn
from fastapi import FastAPI
from app.api.webhook import router as webhook_router
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager
from app.database.mongodb import mongodb

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to MongoDB
    await mongodb.connect()
    yield
    # Shutdown: Close MongoDB Connection
    await mongodb.close()

# Initialize FastAPI application
app = FastAPI(
    title="Instagram Webhook Backend",
    description="FastAPI production-ready server to handle Meta/Instagram Messaging API webhooks.",
    version="0.1.0",
    lifespan=lifespan
)

# Initialize OpenTelemetry
from app.utils.telemetry import init_telemetry
init_telemetry(app)

# Register routes
app.include_router(webhook_router)

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "instagram-webhook-backend",
        "api_version": settings.instagram_api_version,
        "docs_url": "/docs"
    }

def main():
    """
    Main entry point function. Runs uvicorn server.
    """
    logger.info(f"Starting server on {settings.host}:{settings.port}")
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )

if __name__ == "__main__":
    main()
