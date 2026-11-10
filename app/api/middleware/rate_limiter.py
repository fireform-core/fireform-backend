import math
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Initialize the limiter using the client's IP address as the identifier
limiter = Limiter(key_func=get_remote_address)


def _seconds_until_reset(request: Request) -> int:
    """Seconds until the limit that was hit lets requests through again."""
    try:
        limit, args = request.state.view_rate_limit
        reset_at, _ = limiter.limiter.get_window_stats(limit, *args)
        return max(1, math.ceil(reset_at - time.time()))
    except Exception:
        return 60


def setup_rate_limiting(app: FastAPI) -> None:
    """Register rate limiting middleware and error handler on the FastAPI app."""

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # Same {error_code, message} body as every other error, so clients that
    # show `message` (or branch on `error_code`) handle a 429 like the rest.
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        retry_after = _seconds_until_reset(request)
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Too many requests. Limit: {exc.detail}",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
