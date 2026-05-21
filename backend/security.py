import hashlib
import hmac

from fastapi import HTTPException, Request

from config import settings


async def verify_github_signature(request: Request) -> None:
    """
    Verify the X-Hub-Signature-256 header on incoming GitHub webhook requests.
    Raises HTTP 401 if the signature is missing or invalid.
    Skipped entirely if GITHUB_WEBHOOK_SECRET is not configured (dev mode).
    """
    if not settings.github_webhook_secret:
        # Secret not configured — skip verification (useful for local dev)
        return

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    body = await request.body()
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature_header, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
