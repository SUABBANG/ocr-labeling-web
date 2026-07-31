"""KEY 리스트 관리. KEY = {id, name, type}. 루트 keylist.json에 저장.

type: "deid"(비식별화 대상) | "extract"(VALUE 추출).
KEY/VALUE 라벨링에서 VALUE 박스를 그린 뒤 여기서 KEY를 골라 item에 붙인다.
기본값 없음 — 사용자가 KEY 리스트 화면에서 직접 추가한다(keylist.json은 git 제외).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

_STORE = Path(__file__).resolve().parent.parent / "keylist.json"

_TYPES = {"deid", "extract"}


def _write(items: list[dict]) -> None:
    _STORE.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")


def list_keys() -> list[dict]:
    if _STORE.exists():
        return json.loads(_STORE.read_text("utf-8"))
    return []


def _check(name: str, type_: str) -> None:
    if not name.strip():
        raise ValueError("KEY 이름은 필수입니다")
    if type_ not in _TYPES:
        raise ValueError(f"type은 {_TYPES} 중 하나여야 합니다: {type_}")


def add_key(name: str, type_: str) -> dict:
    _check(name, type_)
    k = {"id": uuid.uuid4().hex[:8], "type": type_, "name": name.strip()}
    items = list_keys()
    items.append(k)
    _write(items)
    return k


def update_key(kid: str, name: str, type_: str) -> dict:
    _check(name, type_)
    items = list_keys()
    for k in items:
        if k["id"] == kid:
            k.update(name=name.strip(), type=type_)
            _write(items)
            return k
    raise FileNotFoundError(f"KEY 없음: {kid}")


def delete_key(kid: str) -> None:
    _write([k for k in list_keys() if k["id"] != kid])


def demo() -> None:
    """자체 점검: 기본 빈 목록 + CRUD 라운드트립(임시 store)."""
    global _STORE
    import tempfile

    orig = _STORE
    _STORE = Path(tempfile.mkdtemp()) / "keylist.json"
    try:
        assert list_keys() == []   # 기본값 없음
        k = add_key("계좌번호", "deid")
        assert len(k["id"]) == 8 and len(list_keys()) == 1
        update_key(k["id"], "계좌 번호", "extract")
        got = next(x for x in list_keys() if x["id"] == k["id"])
        assert got["name"] == "계좌 번호" and got["type"] == "extract"
        delete_key(k["id"])
        assert list_keys() == []
        for bad in (("", "deid"), ("x", "nope")):
            try:
                add_key(*bad)
                raise AssertionError(f"검증 미차단: {bad}")
            except ValueError:
                pass
        print("keylist.py OK")
    finally:
        _STORE = orig


if __name__ == "__main__":
    demo()
