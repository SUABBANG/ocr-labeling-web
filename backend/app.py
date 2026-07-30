"""OCR 라벨링 웹 백엔드 (FastAPI).

실행:  uvicorn backend.app:app --reload
정적 프론트(frontend/dist)가 있으면 / 에서 서빙.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, labels, projects  # config: .env 로딩 (import 시점)

app = FastAPI(title="OCR Labeling")


def _guard(fn, *a):
    """헬퍼의 ValueError(경로 밖/검증)/FileNotFound를 HTTP 오류로."""
    try:
        return fn(*a)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# --- 프로젝트 ---
@app.get("/api/projects")
def get_projects():
    return projects.list_projects()


@app.post("/api/projects")
def create_project(data: dict = Body(...)):
    return _guard(projects.add_project, data.get("title", ""),
                  data.get("description", ""), data.get("folder", ""))


@app.put("/api/projects/{pid}")
def edit_project(pid: str, data: dict = Body(...)):
    return _guard(projects.update_project, pid, data.get("title", ""),
                  data.get("description", ""), data.get("folder", ""))


@app.delete("/api/projects/{pid}")
def remove_project(pid: str):
    projects.delete_project(pid)
    return {"ok": True}


@app.put("/api/projects/{pid}/group")
def move_project(pid: str, data: dict = Body(...)):
    """드래그앤드롭: 프로젝트를 폴더에 배치. group=null이면 미분류."""
    return _guard(projects.move_project, pid, data.get("group"))


# --- 프로젝트 폴더(그룹) ---
@app.get("/api/groups")
def get_groups():
    return projects.list_groups()


@app.post("/api/groups")
def create_group(data: dict = Body(...)):
    return _guard(projects.add_group, data.get("name", ""), data.get("description", ""))


@app.put("/api/groups/{gid}")
def edit_group(gid: str, data: dict = Body(...)):
    return _guard(projects.update_group, gid, data.get("name", ""), data.get("description", ""))


@app.delete("/api/groups/{gid}")
def remove_group(gid: str):
    projects.delete_group(gid)
    return {"ok": True}


@app.get("/api/images")
def get_images(folder: str):
    return _guard(labels.list_images, folder)


@app.get("/api/image")
def get_image(folder: str, name: str):
    p = _guard(labels.image_path, folder, name)
    if not p.is_file():
        raise HTTPException(404, "이미지 없음")
    return FileResponse(p)


@app.delete("/api/image")
def delete_image(folder: str, name: str):
    _guard(labels.delete_image, folder, name)
    return {"ok": True}


@app.get("/api/label")
def get_label(folder: str, name: str):
    return _guard(labels.read_label, folder, name)


@app.put("/api/label")
def put_label(folder: str, name: str, data: dict = Body(...)):
    _guard(labels.write_label, folder, name, data)
    return {"ok": True}


@app.post("/api/model")
def run_model(folder: str, name: str, engine: str = "llm", mode: str = "text"):
    """OCR 실행 → 라벨 초안 저장·반환. engine=llm|local, mode=text|cell.

    mode=cell(테이블 셀 탭)은 로컬 모델만 지원. 검출한 셀은 라벨 JSON의 별도 "cells"
    키에 저장하고(텍스트 "words"와 분리) 반대 모드 결과는 실행 시에도 보존한다.
    """
    img = _guard(labels.image_path, folder, name)
    if not img.is_file():
        raise HTTPException(404, "이미지 없음")

    from PIL import Image
    with Image.open(img) as im:
        w, h = im.size

    if mode == "cell":
        try:
            from .table_cell_detection import detect_table_cells
        except ImportError as e:
            raise HTTPException(501, f"로컬 엔진 미설치: {e} (requirements-local.txt)")
        try:
            boxes = detect_table_cells(str(img))
        except Exception as e:  # noqa: BLE001 — 실행 오류를 스택트레이스 대신 메시지로
            raise HTTPException(502, f"테이블 셀 검출 실패: {type(e).__name__}: {e}")
        existing = _guard(labels.read_label, folder, name)
        # 텍스트 "words"는 보존, 레거시로 words에 섞인 셀(kind='cell')은 제거.
        words = [wd for wd in existing.get("words", []) if wd.get("kind") != "cell"]
        cells = [{"id": f"c{i+1}", "kind": "cell",
                  "poly": [[x, y], [x + bw, y], [x + bw, y + bh], [x, y + bh]]}
                 for i, (x, y, bw, bh) in enumerate(boxes)]
        legacy = existing.get("done", False)
        draft = {**existing, "image": name, "width": w, "height": h,
                 "text_done": existing.get("text_done", legacy),
                 "cell_done": existing.get("cell_done", legacy),
                 "words": words, "cells": cells}
        _guard(labels.write_label, folder, name, draft)
        return draft

    if engine == "local":
        try:
            from .pipeline import run_local_ocr
        except ImportError as e:
            raise HTTPException(501, f"로컬 엔진 미설치: {e} (requirements-local.txt)")
        try:
            raw = run_local_ocr(str(img))
        except Exception as e:  # noqa: BLE001 — 실행 오류를 스택트레이스 대신 메시지로
            raise HTTPException(502, f"로컬 모델 실행 실패: {type(e).__name__}: {e}")
        words = [{"id": f"w{i+1}", "text": w_["text"], "poly": w_["poly"]}
                 for i, w_ in enumerate(raw)]
        source = "local"
    else:
        from .llm import run_llm_ocr
        try:
            words, source = run_llm_ocr(str(img), w, h)
        except Exception as e:  # noqa: BLE001 — API/파싱 오류를 클라이언트로 전달
            raise HTTPException(502, f"LLM 실행 실패: {e}")

    existing = _guard(labels.read_label, folder, name)   # 셀 라벨·완료 플래그 보존
    legacy = existing.get("done", False)
    draft = {"image": name, "width": w, "height": h, "source": source,
             "text_done": existing.get("text_done", legacy),
             "cell_done": existing.get("cell_done", legacy),
             "words": words, "cells": existing.get("cells", [])}
    _guard(labels.write_label, folder, name, draft)
    return draft


# --- 정적 프론트 서빙 (빌드됐을 때만) ---
_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
