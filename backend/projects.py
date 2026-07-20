"""프로젝트 관리. 프로젝트 = {제목, 설명, 데이터 폴더 경로}. 루트 projects.json에 저장.

폴더 경로는 서버 기준이라 프로젝트도 서버에 저장(브라우저 아님).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from . import labels

_STORE = Path(__file__).resolve().parent.parent / "projects.json"


def _read() -> list[dict]:
    if _STORE.exists():
        return json.loads(_STORE.read_text("utf-8"))
    return []


def _write(items: list[dict]) -> None:
    _STORE.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def _progress(folder: str) -> dict:
    """폴더의 이미지 총계 + 텍스트/셀 완료 수. 폴더 없으면 None 카운트."""
    try:
        imgs = labels.list_images(folder)
        return {"total": len(imgs),
                "text_done": sum(i["text_done"] for i in imgs),
                "cell_done": sum(i["cell_done"] for i in imgs)}
    except (OSError, ValueError, FileNotFoundError):
        return {"total": None, "text_done": None, "cell_done": None}


def list_projects(with_progress: bool = True) -> list[dict]:
    items = _read()
    if with_progress:
        for p in items:
            p["progress"] = _progress(p["folder"])
    return items


def add_project(title: str, description: str, folder: str) -> dict:
    if not title.strip() or not folder.strip():
        raise ValueError("제목과 폴더 경로는 필수입니다")
    item = {
        "id": uuid.uuid4().hex[:8],
        "title": title.strip(),
        "description": description.strip(),
        "folder": folder.strip(),
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    items = _read()
    items.append(item)
    _write(items)
    return item


def update_project(pid: str, title: str, description: str, folder: str) -> dict:
    items = _read()
    for p in items:
        if p["id"] == pid:
            p.update(title=title.strip(), description=description.strip(),
                     folder=folder.strip())
            _write(items)
            return p
    raise FileNotFoundError(f"프로젝트 없음: {pid}")


def delete_project(pid: str) -> None:
    items = [p for p in _read() if p["id"] != pid]
    _write(items)


def demo() -> None:
    """자체 점검: CRUD 라운드트립(임시 store)."""
    global _STORE
    import tempfile

    orig = _STORE
    _STORE = Path(tempfile.mkdtemp()) / "projects.json"
    try:
        assert list_projects() == []
        p = add_project("테스트", "설명", "/tmp/x")
        assert p["title"] == "테스트" and len(p["id"]) == 8
        assert len(list_projects()) == 1
        update_project(p["id"], "새제목", "", "/tmp/y")
        assert _read()[0]["title"] == "새제목"
        delete_project(p["id"])
        assert list_projects() == []
        try:
            add_project("", "", "")
            raise AssertionError("빈 제목 미차단")
        except ValueError:
            pass
        print("projects.py OK")
    finally:
        _STORE = orig


if __name__ == "__main__":
    demo()
