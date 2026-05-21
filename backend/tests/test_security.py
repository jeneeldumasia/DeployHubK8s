"""
Tests for GitHub webhook signature verification.
"""
import hashlib
import hmac
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_valid_signature_passes():
    """Correct HMAC-SHA256 signature must not raise."""
    secret = "test-secret-abc"
    body = b'{"action": "push"}'
    sig = _make_signature(secret, body)

    mock_request = MagicMock()
    mock_request.headers = {"X-Hub-Signature-256": sig}
    mock_request.body = AsyncMock(return_value=body)

    with patch("security.settings") as mock_settings:
        mock_settings.github_webhook_secret = secret
        from security import verify_github_signature
        # Should complete without raising
        await verify_github_signature(mock_request)


@pytest.mark.asyncio
async def test_wrong_signature_raises_401():
    """Tampered body must raise HTTPException 401."""
    secret = "test-secret-abc"
    body = b'{"action": "push"}'
    wrong_sig = _make_signature(secret, b"tampered-body")

    mock_request = MagicMock()
    mock_request.headers = {"X-Hub-Signature-256": wrong_sig}
    mock_request.body = AsyncMock(return_value=body)

    with patch("security.settings") as mock_settings:
        mock_settings.github_webhook_secret = secret
        from security import verify_github_signature
        with pytest.raises(HTTPException) as exc_info:
            await verify_github_signature(mock_request)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_signature_header_raises_401():
    """Missing X-Hub-Signature-256 header must raise HTTPException 401."""
    mock_request = MagicMock()
    mock_request.headers = {}  # no signature header
    mock_request.body = AsyncMock(return_value=b"{}")

    with patch("security.settings") as mock_settings:
        mock_settings.github_webhook_secret = "some-secret"
        from security import verify_github_signature
        with pytest.raises(HTTPException) as exc_info:
            await verify_github_signature(mock_request)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_no_secret_configured_skips_verification():
    """When GITHUB_WEBHOOK_SECRET is empty, verification is skipped (dev mode)."""
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.body = AsyncMock(return_value=b"{}")

    with patch("security.settings") as mock_settings:
        mock_settings.github_webhook_secret = ""
        from security import verify_github_signature
        # Must not raise
        await verify_github_signature(mock_request)
