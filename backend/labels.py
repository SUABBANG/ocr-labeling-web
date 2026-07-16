"""이미지 폴더 스캔 + 라벨 JSON 읽기/쓰기 + 경로 안전 검사.

폴더 구조:  <folder>/images/*.png|jpg   <folder>/labels/<stem>.json
"""
from __future__ import annotations

import json
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _safe_under(folder: str, *parts: str) -> Path:
    """folder 하위 경로만 허용. path traversal(../) 차단."""
    base = Path(folder).resolve()
    target = base.joinpath(*parts).resolve()
    if base != target and base not in target.parents:
        raise ValueError(f"경로가 folder 밖입니다: {target}")
    return target


def images_dir(folder: str) -> Path:
    return _safe_under(folder, "images")


def labels_dir(folder: str) -> Path:
    return _safe_under(folder, "labels")


def image_path(folder: str, name: str) -> Path:
    return _safe_under(folder, "images", name)


def label_path(folder: str, name: str) -> Path:
    return _safe_under(folder, "labels", Path(name).stem + ".json")


def list_images(folder: str) -> list[dict]:
    """이미지 파일명 + 라벨 존재 여부 + done 플래그."""
    idir = images_dir(folder)
    if not idir.is_dir():
        raise FileNotFoundError(f"images 폴더 없음: {idir}")
    out: list[dict] = []
    for p in sorted(idir.iterdir()):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        lp = label_path(folder, p.name)
        done = False
        if lp.exists():
            try:
                done = bool(json.loads(lp.read_text("utf-8")).get("done", False))
            except (OSError, json.JSONDecodeError):
                done = False
        out.append({"name": p.name, "has_label": lp.exists(), "done": done})
    return out


def read_label(folder: str, name: str) -> dict:
    """라벨 JSON. 없으면 빈 words 골격 반환."""
    lp = label_path(folder, name)
    if lp.exists():
        return json.loads(lp.read_text("utf-8"))
    return {"image": name, "source": "manual", "done": False, "words": []}


def write_label(folder: str, name: str, data: dict) -> None:
    """라벨 JSON 전체 덮어쓰기. labels/ 없으면 생성."""
    lp = label_path(folder, name)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def delete_image(folder: str, name: str) -> None:
    """이미지 + 해당 라벨 파일 삭제(있으면)."""
    for p in (image_path(folder, name), label_path(folder, name)):
        if p.exists():
            p.unlink()


def demo() -> None:
    """자체 점검: 경로 안전 + 라운드트립."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "images").mkdir()
        (Path(d) / "images" / "a.png").write_bytes(b"x")
        assert list_images(d) == [{"name": "a.png", "has_label": False, "done": False}]
        lbl = {"image": "a.png", "source": "manual", "done": True, "words": [
            {"id": "w1", "text": "hi", "poly": [[0, 0], [1, 0], [1, 1], [0, 1]]}]}
        write_label(d, "a.png", lbl)
        assert read_label(d, "a.png") == lbl
        assert list_images(d)[0]["done"] is True
        try:
            _safe_under(d, "..", "etc")
            raise AssertionError("traversal 미차단")
        except ValueError:
            pass
        delete_image(d, "a.png")
        assert list_images(d) == []
    print("labels.py OK")


if __name__ == "__main__":
    demo()
