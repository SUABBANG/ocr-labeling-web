"""인식 모듈 (메인 프로세스 측). paddle을 직접 import하지 않는다.

torch(검출)와 paddle(인식)은 같은 프로세스에서 cuDNN DLL 충돌로 공존 불가라,
인식은 상주 워커 서브프로세스(worker.py)에서 수행하고 여기서는 그 관리만 한다.
덕분에 검출은 메인에서 GPU, 인식은 워커에서 GPU를 각각 쓸 수 있다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

MARKER = "@@R@@"  # 워커 응답 라인 접두사 (worker.py와 공유)

_ROOT = Path(__file__).resolve().parent.parent.parent
_proc = None
_lock = threading.Lock()


def _worker():
    """상주 워커를 lazy 기동/재기동."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        return _proc
    # 바이너리 파이프: 워커 stdout에 섞이는 CP949 로그 노이즈를 utf-8 디코딩 없이 통과시킨다.
    _proc = subprocess.Popen(
        [sys.executable, "-m", "backend.recognition.worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=str(_ROOT),
    )
    return _proc


_MARKER_B = MARKER.encode("utf-8")


def _roundtrip(req: dict) -> dict:
    """워커에 요청 1건을 보내고 마커 응답을 파싱해 돌려준다."""
    with _lock:  # ponytail: 단일 워커 직렬화 — 처리량 필요하면 워커 풀로
        proc = _worker()
        proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()          # bytes
            if line == b"":
                raise RuntimeError("인식 워커가 종료되었습니다 (stderr 로그 확인)")
            if line.startswith(_MARKER_B):          # 마커 라인만 파싱, 노이즈는 스킵
                out = json.loads(line[len(_MARKER_B):].decode("utf-8"))
                break
    if "error" in out:
        raise RuntimeError(out["error"])
    return out


def recognize(image_path: str, boxes: list[list[int]]) -> list[str]:
    """워커에 이미지 경로 + 박스를 보내 텍스트 리스트를 받는다."""
    if not boxes:
        return []
    return _roundtrip({"path": image_path, "boxes": boxes})["texts"]
