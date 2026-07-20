"""설정 로딩. API 키·경로는 프로젝트 루트 `.env`에서 관리(있으면).

python-dotenv 미설치/파일 없음이면 실제 환경변수로 폴백.
API 키(ANTHROPIC_API_KEY/OPENAI_API_KEY)는 os.environ에 실려 SDK가 직접 읽는다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def read_model_name(model_dir: str) -> "str | None":
    """model_dir/inference.yml의 model_name을 읽는다(paddle 모델 mismatch 방지)."""
    p = Path(model_dir) / "inference.yml"
    try:
        m = re.search(r"model_name:\s*(\S+)", p.read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except OSError:
        return None

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass  # 실제 환경변수 사용

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "claude").lower()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")

def _first(subdir: str, want_dir: bool) -> str:
    """model/<subdir> 안의 첫 파일(가중치)/디렉토리 경로. 파일명은 소스에 고정하지 않음."""
    d = _ROOT / "model" / subdir
    if d.is_dir():
        hits = sorted(p for p in d.iterdir() if p.is_dir() == want_dir)
        if hits:
            return str(hits[0])
    return str(d)


# 모델 경로: env 우선, 없으면 model/det·model/rec 안에서 자동 탐색.
DET_MODEL_PATH = os.getenv("DET_MODEL_PATH") or _first("det", want_dir=False)
REC_MODEL_DIR = os.getenv("REC_MODEL_DIR") or _first("rec", want_dir=True)

# 테이블 셀 검출 모델(paddle). model/table/<모델디렉토리> 자동 탐색, model_name은 inference.yml.
# 셀 탭 로컬 모델 실행 전용(인식과 같은 paddle 워커에서 구동).
TABLE_MODEL_DIR = os.getenv("TABLE_MODEL_DIR") or _first("table", want_dir=True)
TABLE_CELL_THRESH = float(os.getenv("TABLE_CELL_THRESH", "0.5"))  # inference.yml draw_threshold

# 인식 실행 디바이스. 빈 값=자동(가능하면 GPU, 실패 시 CPU 폴백). 강제하려면 cpu|gpu.
REC_DEVICE = os.getenv("REC_DEVICE", "").strip()

# 로컬 검출 후처리: 박스를 우/하단으로 넓히는 패딩(박스 높이 대비 비율).
# 검출 박스가 글자를 약간 타이트하게 잡는 경향 보정. 값은 이미지/모델에 맞춰 조정.
# ponytail: 상수 대신 env 노브 — 데이터셋마다 최적 패딩이 달라 캘리브레이션 필요.
BOX_PAD_X = float(os.getenv("BOX_PAD_X", "0.10"))  # 오른쪽
BOX_PAD_Y = float(os.getenv("BOX_PAD_Y", "0.15"))  # 아래
