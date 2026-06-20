# src/api/webhook.py
import hashlib
import hmac
import json
import logging
from fastapi import APIRouter, Request, HTTPException
from src.config import Settings
from src.services.webhook import process_issue_event

router = APIRouter()
logger = logging.getLogger(__name__)


def verify_signature(secret: str, body: bytes, signature_header: str) -> bool:
    if not signature_header:
        return False
    try:
        mac = hmac.new(secret.encode(), body, hashlib.sha256)
        expected = f"sha256={mac.hexdigest()}"
        return hmac.compare_digest(expected, signature_header)
    except Exception:
        return False


@router.post("/webhook/github")
async def github_webhook(request: Request):
    settings = Settings()
    event_type = request.headers.get("X-GitHub-Event", "")

    if event_type == "ping":
        return {"message": "pong"}

    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature")

    if settings.github_webhook_secret:
        if not verify_signature(settings.github_webhook_secret, body, signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(body)
    logger.info(f"Received webhook: {event_type}, delivery: {request.headers.get('X-GitHub-Delivery')}")

    if event_type == "issues":
        result = await process_issue_event(event_type, payload)
        return result

    elif event_type == "issue_comment":
        return {"status": "ok", "event": "issue_comment"}

    elif event_type == "pull_request":
        return {"status": "ok", "event": "pull_request"}

    return {"status": "ignored", "event": event_type}
