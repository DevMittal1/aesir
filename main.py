import logging
import uvicorn
from anyio import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.api.webhook import router as webhook_router
from app.api.admin import router as admin_router
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
from app.services.webhook_queue import webhook_queue

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Connect to MongoDB and start worker queue
    await mongodb.connect()
    await webhook_queue.start()
    yield
    # Shutdown: Stop worker queue and close MongoDB Connection
    await webhook_queue.stop()
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
app.include_router(admin_router)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    index_file = Path("app") / "static" / "index.html"
    if await index_file.exists():
        content = await index_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>Dashboard is setting up... Please check back in a moment.</h1>")

@app.get("/api/health")
async def health():
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
