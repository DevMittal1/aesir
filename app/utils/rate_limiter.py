import time
import logging
from typing import Dict, List
from fastapi import Request, HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)

def get_client_ip(request: Request) -> str:
    """
    Safely extract client IP address, checking X-Forwarded-For header first.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Retrieve the original client IP (first element in X-Forwarded-For chain)
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


class InMemorySlidingWindowRateLimiter:
    def __init__(self):
        # Maps client IP to a list of timestamps of recent requests
        self.requests: Dict[str, List[float]] = {}

    async def check_rate_limit(self, request: Request) -> None:
        """
        Check if the incoming request exceeds the configured rate limits.
        Raises HTTP 429 Too Many Requests if the limit is exceeded.
        """
        client_ip = get_client_ip(request)
        current_time = time.time()
        
        limit_calls = settings.rate_limit_calls
        period = settings.rate_limit_period_seconds
        
        # Initialize or fetch list of timestamps
        timestamps = self.requests.get(client_ip, [])
        
        # Filter out timestamps older than the rate limit period
        cutoff = current_time - period
        timestamps = [t for t in timestamps if t > cutoff]
        
        if len(timestamps) >= limit_calls:
            logger.warning(f"Rate limit exceeded for IP {client_ip}. Requests in window: {len(timestamps)}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later."
            )
            
        # Record new request timestamp
        timestamps.append(current_time)
        self.requests[client_ip] = timestamps

# Limiter instance
rate_limiter = InMemorySlidingWindowRateLimiter()
