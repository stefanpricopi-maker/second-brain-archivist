"""OCR pentru PDF-uri scanate (Tesseract + pdf2image). Necesită binare: tesseract, poppler."""

from __future__ import annotations

import os
from typing import Any

# Limbi Tesseract: ex. "ron+eng" (vezi `tesseract --list-langs`).
DEFAULT_OCR_LANG = (os.getenv("OCR_LANG") or "ron+eng").strip() or "ron+eng"
DEFAULT_OCR_DPI = max(72, min(400, int(os.getenv("OCR_DPI") or "200")))


def ocr_backend_status() -> dict[str, Any]:
    """Raport pentru UI / status: dependențe Python și binar tesseract."""
    try:
        import pytesseract  # noqa: WPS433
        from pdf2image import convert_from_bytes  # noqa: WPS433, F401
    except ImportError as e:
        return {"ok": False, "python_ok": False, "tesseract_ok": False, "detail": str(e)}
    try:
        import pytesseract

        ver = pytesseract.get_tesseract_version()
        return {
            "ok": True,
            "python_ok": True,
            "tesseract_ok": True,
            "tesseract_version": str(ver),
            "ocr_lang": DEFAULT_OCR_LANG,
            "ocr_dpi": DEFAULT_OCR_DPI,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "python_ok": True,
            "tesseract_ok": False,
            "detail": str(e),
            "hint": "Instalează pachetul «tesseract» (ex: brew install tesseract pe macOS, apt install tesseract-ocr pe Ubuntu).",
        }


def ocr_pdf_pages(*, content: bytes, dpi: int | None = None, lang: str | None = None) -> list[str]:
    """
    Convertește fiecare pagină PDF în imagine și aplică OCR.
    Ridică RuntimeError dacă lipsesc dependențele sau OCR eșuează complet.
    """
    import pytesseract  # noqa: WPS433
    from pdf2image import convert_from_bytes  # noqa: WPS433

    st = ocr_backend_status()
    if not st.get("ok"):
        raise RuntimeError(st.get("detail") or "OCR indisponibil")

    dpi_use = int(dpi or DEFAULT_OCR_DPI)
    lang_use = (lang or DEFAULT_OCR_LANG).strip() or DEFAULT_OCR_LANG
    images = convert_from_bytes(content, dpi=dpi_use)
    pages: list[str] = []
    for im in images:
        try:
            txt = pytesseract.image_to_string(im, lang=lang_use) or ""
        except Exception as e:  # noqa: BLE001
            txt = ""
            err = str(e)
            if "tessdata" in err.lower() or "traineddata" in err.lower():
                raise RuntimeError(
                    f"OCR: limbi lipsă pentru «{lang_use}». Instalează pachetele tesseract pentru limbile folosite "
                    f"sau setează OCR_LANG=eng în .env. Detaliu: {err}"
                ) from e
        pages.append(txt.strip())
    return pages
