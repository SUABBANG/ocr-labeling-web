"""LLM OCR 엔진 (Claude / GPT). 비전 모델에 단어 단위 OCR을 요청.

설정: backend/config.py (.env) — LLM_PROVIDER, CLAUDE_MODEL, GPT_MODEL,
      ANTHROPIC_API_KEY / OPENAI_API_KEY.
self-check:  python -m backend.llm
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re

from ..config import CLAUDE_MODEL, GPT_MODEL, LLM_PROVIDER

PROMPT = (
    "이 이미지의 모든 텍스트를 단어 단위로 읽어라. 각 단어마다 텍스트와 픽셀 좌표"
    " 경계상자 [x1,y1,x2,y2] (좌상단 원점, 정수)를 구하라. 이미지 크기는 {w}x{h}."
    ' 오직 JSON만 출력: {{"words":[{{"text":"...","box":[x1,y1,x2,y2]}}]}}'
)


def _b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


def _extract_json(text: str) -> dict:
    """모델 응답에서 JSON 오브젝트 추출 (```json 펜스/잡텍스트 허용)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 응답 파싱 실패: {text[:200]}")
    return json.loads(m.group(0))


def _box_to_poly(box: list) -> list[list[int]]:
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _to_words(parsed: dict) -> list[dict]:
    words = []
    for i, w in enumerate(parsed.get("words", [])):
        box = w.get("box")
        if not (isinstance(box, list) and len(box) == 4):
            continue
        words.append({"id": f"w{i+1}", "text": str(w.get("text", "")),
                      "poly": _box_to_poly(box)})
    return words


def _run_claude(image_bytes: bytes, media_type: str, w: int, h: int) -> list[dict]:
    import anthropic  # lazy

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": media_type, "data": _b64(image_bytes)}},
            {"type": "text", "text": PROMPT.format(w=w, h=h)},
        ]}],
    )
    return _to_words(_extract_json(resp.content[0].text))


def _run_gpt(image_bytes: bytes, media_type: str, w: int, h: int) -> list[dict]:
    from openai import OpenAI  # lazy

    client = OpenAI()
    data_url = f"data:{media_type};base64,{_b64(image_bytes)}"
    resp = client.chat.completions.create(
        model=GPT_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(w=w, h=h)},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    )
    return _to_words(_extract_json(resp.choices[0].message.content))


def run_llm_ocr(image_path: str, width: int, height: int) -> tuple[list[dict], str]:
    """이미지 → 단어 리스트 + source 문자열('claude'|'gpt')."""
    media_type = mimetypes.guess_type(image_path)[0] or "image/png"
    image_bytes = open(image_path, "rb").read()
    if LLM_PROVIDER == "gpt":
        return _run_gpt(image_bytes, media_type, width, height), "gpt"
    return _run_claude(image_bytes, media_type, width, height), "claude"


def demo() -> None:
    """자체 점검: 파싱/변환만 (API 호출 없음)."""
    parsed = _extract_json('노이즈 ```json\n{"words":[{"text":"hi","box":[1,2,3,4]}]}\n``` 끝')
    words = _to_words(parsed)
    assert words == [{"id": "w1", "text": "hi", "poly": [[1, 2], [3, 2], [3, 4], [1, 4]]}]
    assert _to_words({"words": [{"text": "x", "box": [1, 2]}]}) == []
    print("llm OK")


if __name__ == "__main__":
    demo()
