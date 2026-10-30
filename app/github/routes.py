"""POST /hooks/github — outside /api: GitHub authenticates with the HMAC signature
(X-Hub-Signature-256 over the raw body with GITHUB_WEBHOOK_SECRET), not a bearer token."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_primary_db
from app.github.services.webhook_service import WebhookService, signature_ok
from app.initiatives.services.record_service import RecordService
from config.settings import settings

router = APIRouter(prefix="/hooks", tags=["webhooks"])


@router.post("/github")
async def github_webhook(request: Request, db: Annotated[Session, Depends(get_primary_db)]):
    secret = settings.github.GITHUB_WEBHOOK_SECRET
    if not secret:
        return JSONResponse({"title": "GITHUB_WEBHOOK_SECRET is not configured", "status": 503}, status_code=503)
    body = await request.body()
    if not signature_ok(secret, body, request.headers.get("x-hub-signature-256")):
        return JSONResponse({"title": "bad or missing X-Hub-Signature-256", "status": 401}, status_code=401)
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return JSONResponse({"title": "body is not JSON (set the webhook content type to application/json)", "status": 400}, status_code=400)
    event = request.headers.get("x-github-event", "")
    delivery = request.headers.get("x-github-delivery", "")
    outcome = WebhookService(RecordService(db)).handle(event, delivery, payload)
    return {"event": event, "delivery": delivery, **outcome.to_dict()}
