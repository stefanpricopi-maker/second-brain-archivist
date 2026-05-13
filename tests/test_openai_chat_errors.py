from __future__ import annotations

import httpx
from openai import APIStatusError, RateLimitError


def test_rate_limit_maps_to_503_with_romanian_hint() -> None:
    from app.main import openai_chat_error_to_http

    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(
        429,
        request=req,
        json={"error": {"message": "quota", "code": "insufficient_quota", "type": "insufficient_quota"}},
    )
    exc = RateLimitError("limit", response=resp, body=resp.json())
    http = openai_chat_error_to_http(exc)
    assert http.status_code == 503
    assert "429" in http.detail
    assert "billing" in http.detail.lower() or "facturare" in http.detail.lower()
    assert "LLM_MODE=disabled" in http.detail


def test_api_status_429_insufficient_quota_maps_to_503() -> None:
    from app.main import openai_chat_error_to_http

    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(
        429,
        request=req,
        json={"error": {"message": "You exceeded", "code": "insufficient_quota"}},
    )
    exc = APIStatusError("limit", response=resp, body=resp.json())
    http = openai_chat_error_to_http(exc)
    assert http.status_code == 503
