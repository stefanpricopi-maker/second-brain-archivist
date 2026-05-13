"""OCR pentru PDF-uri scanate (Tesseract + pdf2image). Necesită binare: tesseract, poppler."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Limbi Tesseract: cod ISO 639-2 (română = `ron`). Pentru text mixt ro+en: `ron+eng`. Vezi `tesseract --list-langs`.
# macOS: `brew install tesseract-lang` pentru pachete de limbă (inclusiv română).
DEFAULT_OCR_LANG = (os.getenv("OCR_LANG") or "ron").strip() or "ron"
# 240 DPI e un compromis bun calitate/timp față de 200; max 400 pentru scanări slabe (mai lent la ingest).
DEFAULT_OCR_DPI = max(72, min(400, int(os.getenv("OCR_DPI") or "240")))


def _ocr_image_preprocess_enabled() -> bool:
    v = (os.getenv("OCR_IMAGE_PREPROCESS") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _ocr_tesseract_config() -> str | None:
    """Ex.: `--oem 3 --psm 6` pentru bloc de text continuu; lasă gol pentru default Tesseract."""
    c = (os.getenv("OCR_TESSERACT_CONFIG") or "").strip()
    return c or None


def _prepare_image_for_ocr(im: Any) -> Any:
    """Grayscale + autocontrast — ajută pe scanări estompate."""
    from PIL import ImageOps

    g = im.convert("L")
    return ImageOps.autocontrast(g, cutoff=1)


def _resolve_poppler_bin_dir() -> str | None:
    """
    Directorul care conține `pdftoppm` (pdf2image îl folosește pentru PDF→PNG).
    Pe macOS, același caz ca la Tesseract: IDE fără `/opt/homebrew/bin` în PATH.
    """
    explicit = (os.getenv("POPPLER_PATH") or os.getenv("POPPLER_BIN") or "").strip()
    if explicit:
        exp = os.path.expanduser(explicit)
        p = Path(exp)
        if p.is_dir() and (p / "pdftoppm").is_file():
            return str(p.resolve())
        if p.is_file() and p.name == "pdftoppm":
            return str(p.parent.resolve())
        w = shutil.which(exp)
        if w and Path(w).name == "pdftoppm":
            return str(Path(w).parent.resolve())
    w = shutil.which("pdftoppm")
    if w:
        return str(Path(w).parent.resolve())
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
        if (Path(d) / "pdftoppm").is_file():
            return d
    return None


def _resolve_tesseract_executable() -> str | None:
    """
    Găsește binarul `tesseract`. Pe macOS, procesele pornite din IDE adesea nu au
    `/opt/homebrew/bin` în PATH — încercăm căi uzuale Homebrew + variabile `.env`.
    """
    explicit = (os.getenv("TESSERACT_CMD") or os.getenv("OCR_TESSERACT_CMD") or "").strip()
    if explicit:
        p = Path(expanded := os.path.expanduser(explicit))
        if p.is_file():
            return str(p.resolve())
        if shutil.which(expanded):
            return shutil.which(expanded)
    w = shutil.which("tesseract")
    if w:
        return w
    for candidate in (
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/local/bin/tesseract",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _configure_pytesseract() -> str | None:
    """Setează `pytesseract.pytesseract.tesseract_cmd`; returnează calea folosită sau None."""
    import pytesseract  # noqa: WPS433

    path = _resolve_tesseract_executable()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
    return path


def _resolve_ocrmypdf_executable() -> str | None:
    """
    Găsește CLI `ocrmypdf` (pip instalează scriptul în același `bin` ca `python`;
    pe macOS Homebrew poate fi doar în `/opt/homebrew/bin`).
    """
    explicit = (os.getenv("OCRMYPDF_CMD") or os.getenv("OCR_OCRMYPDF_CMD") or "").strip()
    if explicit:
        exp = os.path.expanduser(explicit)
        p = Path(exp)
        if p.is_file():
            return str(p.resolve())
        w = shutil.which(exp)
        if w:
            return w
    w = shutil.which("ocrmypdf")
    if w:
        return w
    bindir = Path(sys.executable).resolve().parent
    name = "ocrmypdf.exe" if sys.platform.startswith("win") else "ocrmypdf"
    candidate = bindir / name
    if candidate.is_file():
        return str(candidate)
    for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
        p = Path(d) / "ocrmypdf"
        if p.is_file():
            return str(p.resolve())
    return None


def ocr_backend_status() -> dict[str, Any]:
    """Raport pentru UI / status: dependențe Python și binar tesseract."""
    try:
        import pytesseract  # noqa: WPS433
        from pdf2image import convert_from_bytes  # noqa: WPS433, F401
    except ImportError as e:
        return {"ok": False, "python_ok": False, "tesseract_ok": False, "detail": str(e)}
    try:
        import pytesseract

        resolved = _configure_pytesseract()
        if not resolved:
            return {
                "ok": False,
                "python_ok": True,
                "tesseract_ok": False,
                "tesseract_path": None,
                "detail": "Nu găsesc binarul «tesseract» (PATH gol sau Homebrew neinclus).",
                "hint": (
                    "macOS: `brew install tesseract tesseract-lang poppler`, apoi repornește serverul. "
                    "Dacă tot nu merge, setează în .env: TESSERACT_CMD=/opt/homebrew/bin/tesseract "
                    "(sau `/usr/local/bin/tesseract` pe Intel). Ubuntu: `apt install tesseract-ocr tesseract-ocr-ron "
                    "tesseract-ocr-eng poppler-utils`."
                ),
            }

        ver = pytesseract.get_tesseract_version()
        poppler_dir = _resolve_poppler_bin_dir()
        if not poppler_dir:
            return {
                "ok": False,
                "python_ok": True,
                "tesseract_ok": True,
                "tesseract_path": resolved,
                "tesseract_version": str(ver),
                "poppler_ok": False,
                "poppler_path": None,
                "ocr_lang": DEFAULT_OCR_LANG,
                "ocr_dpi": DEFAULT_OCR_DPI,
                "detail": "Nu găsesc «pdftoppm» (Poppler) — pdf2image nu poate citi PDF-ul.",
                "hint": (
                    "macOS: `brew install poppler` (deja instalat la tine = cale lipsă din PATH). "
                    "Pune în `.env`: `POPPLER_PATH=/opt/homebrew/bin` (Apple Silicon) sau `/usr/local/bin` (Intel), apoi repornește serverul."
                ),
            }
        ocrm = _resolve_ocrmypdf_executable()
        return {
            "ok": True,
            "python_ok": True,
            "tesseract_ok": True,
            "tesseract_path": resolved,
            "tesseract_version": str(ver),
            "poppler_ok": True,
            "poppler_path": poppler_dir,
            "ocr_lang": DEFAULT_OCR_LANG,
            "ocr_dpi": DEFAULT_OCR_DPI,
            "ocr_image_preprocess": _ocr_image_preprocess_enabled(),
            "ocr_tesseract_config": _ocr_tesseract_config(),
            "ocrmypdf_available": ocrm is not None,
            "ocrmypdf_path": ocrm,
            "ocrmypdf_hint": (
                None
                if ocrm
                else (
                    "Pune în venv: `pip install ocrmypdf` (deja în requirements.txt), apoi repornește serverul. "
                    "Linux/Docker: `apt install ghostscript qpdf`. macOS: `brew install ghostscript qpdf` "
                    "sau `brew install ocrmypdf`. Opțional în .env: `OCRMYPDF_CMD=/cale/către/ocrmypdf`."
                )
            ),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "python_ok": True,
            "tesseract_ok": False,
            "tesseract_path": _resolve_tesseract_executable(),
            "detail": str(e),
            "hint": (
                "Instalează Tesseract și poppler (vezi README). Pe macOS cu Homebrew: "
                "`brew install tesseract tesseract-lang poppler`. Opțional: `TESSERACT_CMD=/opt/homebrew/bin/tesseract` în .env."
            ),
        }


def ocr_pdf_pages(*, content: bytes, dpi: int | None = None, lang: str | None = None) -> list[str]:
    """
    Convertește fiecare pagină PDF în imagine și aplică OCR.
    Ridică RuntimeError dacă lipsesc dependențele sau OCR eșuează complet.
    """
    import pytesseract  # noqa: WPS433
    from pdf2image import convert_from_bytes  # noqa: WPS433

    _configure_pytesseract()
    st = ocr_backend_status()
    if not st.get("ok"):
        raise RuntimeError(st.get("detail") or "OCR indisponibil")

    dpi_use = int(dpi or DEFAULT_OCR_DPI)
    lang_use = (lang or DEFAULT_OCR_LANG).strip() or DEFAULT_OCR_LANG
    tess_cfg = _ocr_tesseract_config()
    preprocess = _ocr_image_preprocess_enabled()
    poppler_dir = _resolve_poppler_bin_dir()
    kwargs: dict[str, Any] = {"dpi": dpi_use}
    if poppler_dir:
        kwargs["poppler_path"] = poppler_dir
    images = convert_from_bytes(content, **kwargs)
    pages: list[str] = []
    for im in images:
        work = _prepare_image_for_ocr(im) if preprocess else im
        try:
            if tess_cfg:
                txt = pytesseract.image_to_string(work, lang=lang_use, config=tess_cfg) or ""
            else:
                txt = pytesseract.image_to_string(work, lang=lang_use) or ""
        except Exception as e:  # noqa: BLE001
            txt = ""
            err = str(e)
            if "tessdata" in err.lower() or "traineddata" in err.lower():
                raise RuntimeError(
                    f"OCR: lipsesc datele de limbă pentru «{lang_use}». Pe macOS: `brew install tesseract-lang` "
                    f"(română: `ron`). Poți seta în .env doar română: `OCR_LANG=ron` sau mixt: `OCR_LANG=ron+eng`. "
                    f"Detaliu: {err}"
                ) from e
        pages.append(txt.strip())
    return pages


def try_run_ocrmypdf(*, content: bytes, lang: str | None = None) -> bytes | None:
    """
    Opțional: rulează `ocrmypdf` (trebuie instalat separat: pip install ocrmypdf + ghostscript + pngquant…
    sau pachetul sistem). Dacă reușește, returnează PDF-ul optimizat cu strat de text; altfel None.
    """
    flag = (os.getenv("OCR_USE_OCRMYPDF") or "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return None
    exe = _resolve_ocrmypdf_executable()
    if not exe:
        return None
    lang_use = ((lang or DEFAULT_OCR_LANG).strip() or DEFAULT_OCR_LANG).replace(" ", "")
    timeout = max(30, int(os.getenv("OCR_OCRMYPDF_TIMEOUT_SEC") or "900"))
    fd_in, path_in = tempfile.mkstemp(suffix=".pdf")
    fd_out, path_out = tempfile.mkstemp(suffix=".pdf")
    os.close(fd_in)
    os.close(fd_out)
    pin = Path(path_in)
    pout = Path(path_out)
    try:
        pin.write_bytes(content)
        try:
            pout.unlink(missing_ok=True)
        except OSError:
            pass
        cmd = [
            exe,
            "--language",
            lang_use,
            "--optimize",
            "0",
            "--skip-text",
            str(pin),
            str(pout),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if proc.returncode != 0:
            log.info(
                "ocrmypdf eșuat (rc=%s): %s",
                proc.returncode,
                (proc.stderr or b"").decode("utf-8", errors="replace")[:500],
            )
            return None
        if not pout.is_file() or pout.stat().st_size < 64:
            return None
        return pout.read_bytes()
    except subprocess.TimeoutExpired:
        log.warning("ocrmypdf timeout după %s s", timeout)
        return None
    except OSError as e:
        log.warning("ocrmypdf eroare IO: %s", e)
        return None
    finally:
        for p in (pin, pout):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
