from __future__ import annotations

from pathlib import Path


def assert_under_base(*, base: Path, target: Path) -> Path:
    """
    Verifică că `target` (rezolvat) rămâne sub `base` (rezolvat).
    Protejează împotriva `..` și a căilor absolute în componente.
    """
    base_r = base.expanduser().resolve()
    tgt = target.expanduser().resolve()
    if tgt == base_r:
        return tgt
    if base_r not in tgt.parents:
        raise ValueError("path outside allowed base")
    return tgt


def sanitize_subdir(sub: str | None) -> str:
    """Păstrează doar segmente relative sigure (fără .., goluri, absolute)."""
    if not sub:
        return ""
    raw = str(sub).strip().replace("\\", "/")
    if raw.startswith("/"):
        return ""
    parts: list[str] = []
    for seg in raw.split("/"):
        seg = seg.strip()
        if not seg or seg == ".":
            continue
        if seg == ".." or ".." in seg:
            continue
        if seg.startswith(("/", "\\")):
            continue
        parts.append(seg)
    return "/".join(parts)


def resolve_export_download(exports_dir: Path, rel_path: str) -> Path:
    """
    Rezolvă calea relativă pentru GET /archive/files/... sub EXPORTS_DIR.
    """
    rel = (rel_path or "").strip()
    if not rel or "\x00" in rel:
        raise ValueError("invalid path")
    if rel.startswith(("/", "\\")):
        raise ValueError("invalid path")
    for p in Path(rel).parts:
        if p == ".." or p == ".":
            raise ValueError("invalid path")
    base = exports_dir.expanduser().resolve()
    target = (base / rel).resolve()
    assert_under_base(base=base, target=target)
    return target
