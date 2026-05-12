"""Căi fixe în biblioteca Drive după extensia fișierului (fără LLM)."""

from __future__ import annotations

from pathlib import Path


def extension_destination_segments(file_name: str) -> tuple[str, list[str]]:
    """
    Returnează (etichetă UI, segmente de folder sub rădăcina bibliotecii).

    Reguli:
    - .pdf → PDF
    - .doc, .docx → Documente
    - .png, .jpeg, .jpg → Afise
    - .ppt, .pptx → Powerpoint
    - altceva → Altele
    """
    ext = Path(file_name or "").suffix.lower()
    if ext == ".pdf":
        return "PDF", ["PDF"]
    if ext in (".doc", ".docx"):
        return "Documente", ["Documente"]
    if ext in (".png", ".jpeg", ".jpg", ".jpe"):
        return "Afise", ["Afise"]
    if ext in (".ppt", ".pptx"):
        return "PowerPoint", ["Powerpoint"]
    return "Altele", ["Altele"]
