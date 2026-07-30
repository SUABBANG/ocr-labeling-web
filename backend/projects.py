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
_GROUPS = Path(__file__).resolve().parent.parent / "groups.json"


def _read() -> list[dict]:
    if _STORE.exists():
        return json.loads(_STORE.read_text("utf-8"))
    return []


def _write(items: list[dict]) -> None:
    _STORE.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def _read_groups() -> list[dict]:
    if _GROUPS.exists():
        return json.loads(_GROUPS.read_text("utf-8"))
    return []


def _write_groups(items: list[dict]) -> None:
    _GROUPS.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


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


# --- 프로젝트 폴더(그룹) ---
def list_groups() -> list[dict]:
    return _read_groups()


def add_group(name: str, description: str = "") -> dict:
    if not name.strip():
        raise ValueError("폴더명은 필수입니다")
    g = {"id": uuid.uuid4().hex[:8], "name": name.strip(),
         "description": description.strip(),
         "created": datetime.now().isoformat(timespec="seconds")}
    items = _read_groups()
    items.append(g)
    _write_groups(items)
    return g


def update_group(gid: str, name: str, description: str = "") -> dict:
    items = _read_groups()
    for g in items:
        if g["id"] == gid:
            g.update(name=name.strip(), description=description.strip())
            _write_groups(items)
            return g
    raise FileNotFoundError(f"폴더 없음: {gid}")


def delete_group(gid: str) -> None:
    """폴더 삭제. 소속 프로젝트는 미분류(group=None)로 되돌린다(프로젝트는 유지)."""
    _write_groups([g for g in _read_groups() if g["id"] != gid])
    items = _read()
    changed = False
    for p in items:
        if p.get("group") == gid:
            p["group"] = None
            changed = True
    if changed:
        _write(items)


def move_project(pid: str, group: str | None) -> dict:
    """프로젝트를 폴더에 배치(group=None이면 미분류). 드래그앤드롭용."""
    if group is not None and group not in {g["id"] for g in _read_groups()}:
        raise ValueError(f"폴더 없음: {group}")
    items = _read()
    for p in items:
        if p["id"] == pid:
            p["group"] = group
            _write(items)
            return p
    raise FileNotFoundError(f"프로젝트 없음: {pid}")


def demo() -> None:
    """자체 점검: 프로젝트/폴더 CRUD + 드래그 이동 라운드트립(임시 store)."""
    global _STORE, _GROUPS
    import tempfile

    orig, orig_g = _STORE, _GROUPS
    d = Path(tempfile.mkdtemp())
    _STORE, _GROUPS = d / "projects.json", d / "groups.json"
    try:
        assert list_projects() == []
        p = add_project("테스트", "설명", "/tmp/x")
        assert p["title"] == "테스트" and len(p["id"]) == 8
        assert len(list_projects()) == 1
        update_project(p["id"], "새제목", "", "/tmp/y")
        assert _read()[0]["title"] == "새제목"
        # 폴더(그룹) + 드래그 이동
        g = add_group("폴더A", "설명")
        assert len(list_groups()) == 1 and len(g["id"]) == 8
        move_project(p["id"], g["id"])
        assert _read()[0]["group"] == g["id"]
        try:
            move_project(p["id"], "없는폴더")
            raise AssertionError("없는 폴더 이동 미차단")
        except ValueError:
            pass
        delete_group(g["id"])   # 폴더 삭제 → 프로젝트는 미분류로 남음
        assert list_groups() == [] and _read()[0]["group"] is None
        delete_project(p["id"])
        assert list_projects() == []
        try:
            add_project("", "", "")
            raise AssertionError("빈 제목 미차단")
        except ValueError:
            pass
        try:
            add_group("")
            raise AssertionError("빈 폴더명 미차단")
        except ValueError:
            pass
        print("projects.py OK")
    finally:
        _STORE, _GROUPS = orig, orig_g


if __name__ == "__main__":
    demo()
