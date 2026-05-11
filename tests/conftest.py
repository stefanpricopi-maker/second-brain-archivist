from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _ci_safe_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evită apeluri OpenAI reale în teste dacă există cheie în mediul local."""
    monkeypatch.setenv("LLM_MODE", "disabled")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
