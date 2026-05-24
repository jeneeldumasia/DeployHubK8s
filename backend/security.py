import hashlib
import hmac
import secrets as _secrets

from fastapi import HTTPException, Request

from config import settings


async def verify_github_signature(request: Request) -> None:
    """
    Verify the X-Hub-Signature-256 header using the global GITHUB_WEBHOOK_SECRET.
    Skipped if the secret is not configured (dev mode).
    """
    if not settings.github_webhook_secret:
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


def verify_project_webhook_signature(body: bytes, signature_header: str, secret: str) -> None:
    """Validate GitHub webhook HMAC for a per-project secret."""
    if not signature_header:
        raise HTTPException(status_code=403, detail="Missing webhook signature")
    provided = signature_header.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")


def generate_webhook_secret() -> str:
    return _secrets.token_urlsafe(32)


def hash_webhook_secret(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def verify_webhook_secret_hash(plain: str, stored_hash: str) -> bool:
    return _secrets.compare_digest(
        hashlib.sha256(plain.encode()).hexdigest(),
        stored_hash,
    )
