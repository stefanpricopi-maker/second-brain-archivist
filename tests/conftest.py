from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ci_safe_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evită apeluri OpenAI reale în teste dacă există cheie în mediul local."""
    monkeypatch.setenv("LLM_MODE", "disabled")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import app.main as main_mod  # noqa: PLC0415

    monkeypatch.setattr(main_mod, "LLM_MODE", "disabled", raising=False)
    monkeypatch.setattr(main_mod, "client", None, raising=False)


@pytest.fixture(autouse=True)
def _disable_rate_limit_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rate limit în memorie poate face 429 între teste dacă rămâne activ."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
