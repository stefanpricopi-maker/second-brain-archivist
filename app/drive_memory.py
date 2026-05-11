from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Placement:
    source_file_id: str
    source_name: str
    preview: str
    target_folder_id: str
    target_folder_name: str
    copied_file_id: str


def memory_path(base: Path) -> Path:
    return base / "placements.json"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"copied_source_ids": [], "placements": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"copied_source_ids": [], "placements": []}
    data.setdefault("copied_source_ids", [])
    data.setdefault("placements", [])
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def already_copied(state: dict[str, Any], source_file_id: str) -> bool:
    return source_file_id in set(state.get("copied_source_ids") or [])


def record_copy(
    path: Path,
    *,
    source_file_id: str,
    source_name: str,
    preview: str,
    target_folder_id: str,
    target_folder_name: str,
    copied_file_id: str,
) -> None:
    st = load_state(path)
    ids: list[str] = list(st.get("copied_source_ids") or [])
    if source_file_id not in ids:
        ids.append(source_file_id)
    st["copied_source_ids"] = ids
    placements: list[dict[str, Any]] = list(st.get("placements") or [])
    placements.append(
        {
            "source_file_id": source_file_id,
            "source_name": source_name,
            "preview": preview[:4000],
            "target_folder_id": target_folder_id,
            "target_folder_name": target_folder_name,
            "copied_file_id": copied_file_id,
        }
    )
    st["placements"] = placements[-200:]
    save_state(path, st)
