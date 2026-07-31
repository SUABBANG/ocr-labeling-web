# OCR 라벨링 웹 도구

로컬 이미지 폴더의 OCR 라벨(박스 + 텍스트)을 브라우저에서 조회·수정하고,
LLM(GPT/Claude) 또는 로컬 모델로 라벨 초안을 생성한다.

기능·데이터 형식·구조 설명: [doc/OVERVIEW.md](doc/OVERVIEW.md)

## 사용 흐름
첫 화면에서 **프로젝트**(제목·설명·데이터 폴더)를 만들고 카드를 열면 라벨링 화면으로 진입.
프로젝트를 **폴더(그룹)**로 묶어 관리할 수 있고(폴더명·설명·생성일), 프로젝트 카드를
드래그앤드롭으로 폴더에 넣거나 `미분류`로 빼낼 수 있다. 폴더 삭제 시 안의 프로젝트는
미분류로 남는다. 프로젝트는 서버 `projects.json`, 폴더는 `groups.json`에 저장된다.

## 백엔드 구조
```
backend/
  app.py          # 메인 (FastAPI 라우팅)
  config.py       # .env 로딩 + 프로바이더/모델 경로
  projects.py     # 프로젝트·폴더(그룹) CRUD (projects.json / groups.json)
  keylist.py      # KEY 리스트 CRUD (keylist.json) — KEY/VALUE 라벨링용
  labels.py       # 라벨 파일 IO
  table_cell_detection/  # 로컬 테이블 셀 검출
  llm/            # LLM 엔진 (Claude/GPT)
  detection/      # 검출 모델
  recognition/    # 인식 모델
  pipeline.py     # 로컬 엔진: detection → recognition
```

## 폴더 구조 (라벨 데이터)
```
<folder>/
  images/   img001.png ...
  labels/   img001.json ...   # 이미지와 동일 stem, 없으면 자동 생성
```

## 라벨 구조 (JSON)
이미지당 JSON 하나. 텍스트 박스(`words`)·테이블 셀(`cells`)·key/value 박스(`item`)는 **별도 배열**로 분리 저장.
```jsonc
{
  "image": "img001.png",
  "width": 892,
  "height": 1253,
  "source": "manual",     // 초안 출처: "manual" | "local" | "gpt" | "claude"
  "text_done": false,     // 텍스트박스 검수 완료
  "cell_done": false,     // 테이블셀 검수 완료
  "item_done": false,     // KEY/VALUE 검수 완료
  "words": [
    {
      "id": "w1",         // 저장 시 배열 순서대로 w1..wN 재번호
      "text": "예시",
      "poly": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],  // 4점 quad, 원본 픽셀 좌표
      "script": "printed" // "printed"(인쇄, 기본) | "handwriting"(필기)
    }
  ],
  "cells": [
    {
      "id": "c1",         // 저장 시 c1..cN 재번호
      "kind": "cell",
      "poly": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]   // 셀은 텍스트 없이 영역만
    }
  ],
  "item": [
    {
      "id": "i1",              // 저장 시 i1..iN 재번호
      "type": "deid",          // "deid"(비식별화 대상) | "extract"(VALUE 추출) — 고른 KEY에서 상속
      "key": { "text": "성명(이름)" },   // KEY 리스트에서 선택 (박스 없음)
      "value": [               // 값 1개 이상, 각각 박스로 라벨
        { "poly": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], "text": "홍길동" }
      ]
    }
  ]
}
```
- **`poly`**: 4점 폴리곤(좌상단→시계방향), 원본 이미지 픽셀 좌표. 축정렬 사각형은 특수 케이스.
- **`item`**: 상단 `KEY/VALUE` 탭에서 라벨링. **KEY는 그리지 않고 KEY 리스트에서 고른다** — 박스로 그리는 건 **VALUE만**. 흐름: `＋VALUE 그리기`로 값 박스를 그리면 KEY 선택창이 뜨고, KEY를 고르면 그 값 1개를 담은 새 `item`이 생성된다. KEY 하나에 값이 여러 개면 오른쪽 바의 `＋value 박스 추가`로 박스를 더 그린다(같은 KEY에 value 누적). KEY 배지를 누르면 KEY를 다시 고를 수 있다. VALUE `text`는 박스 안 `words`를 왼→오로 이어붙여 자동 채우며, 오른쪽 패널·텍스트 탭 수정 시 자동 재수집된다. `type`은 고른 KEY의 종류가 그대로 저장된다. **캔버스 박스·배지 색은 고른 KEY마다 다르게** 칠해진다(KEY 리스트 순서 기준 팔레트, `frontend/src/keycolors.js`).
- **KEY 리스트**: 첫 프로젝트 화면의 `🔑 KEY 리스트` 버튼에서 종류별(비식별화 대상 / VALUE 추출)로 추가·수정·삭제. 서버 `keylist.json`에 저장(기본값 없음 = 빈 목록에서 시작, git 제외). API: `GET/POST /api/keylist`, `PUT/DELETE /api/keylist/{id}`.
- **`text_done` / `cell_done` / `item_done`**: 종류별 검수 완료 플래그. 이미지 리스트 체크박스(텍스트=파랑, 셀=주황, KEY/VALUE=보라)·진행률에 사용. 단축키 `C`는 현재 탭 기준 토글. (구 단일 `done`은 읽을 때 text/cell 둘 다로 폴백)
- 저장 = 파일 전체 덮어쓰기(부분 patch 없음). IO 어댑터는 `backend/labels.py`.

## 실행

### 백엔드
```
pip install -r requirements.txt
copy .env.example .env      # API 키 입력 (ANTHROPIC_API_KEY 또는 OPENAI_API_KEY + LLM_PROVIDER)
uvicorn backend.app:app --reload --reload-exclude projects.json --reload-exclude groups.json   # http://localhost:8000
# projects.json·groups.json은 데이터 파일(요청마다 다시 읽음) → 저장 시 불필요한 재시작 방지
```
API 키는 `.env`로 관리(git 제외). 실제 환경변수로도 가능.

### 프론트 (개발)
```
cd frontend
npm install
npm run dev            # http://localhost:5173  (/api → 8000 프록시)
```
배포 시 `npm run build` → 백엔드가 `frontend/dist`를 `/`에서 서빙.

## 로컬 모델 엔진 (선택)
```
pip install -r requirements-local.txt
```
모델 파일 배치:
- 검출 모델 → `model/det/`
- 인식 모델 → `model/rec/`

경로는 환경변수 `DET_MODEL_PATH` / `REC_MODEL_DIR`로 지정/오버라이드. 미설치 시 `engine=local`은 501.

### torch ↔ paddle 프로세스 분리 (중요)
검출과 인식은 서로 다른 딥러닝 프레임워크(PyTorch / PaddlePaddle)를 쓰는데, 두 GPU 휠이 각각
cuDNN 9를 번들해 **같은 프로세스에서 동시에 못 올린다**(`WinError 127 cudnn_engines_precompiled64_9.dll`).
그래서:
- 검출(torch)은 **메인 프로세스**에서 실행.
- 인식(paddle)은 **상주 워커 서브프로세스**(`backend/recognition/worker.py`)에서 실행하며,
  워커는 `torch`를 import되지 않게 막아(paddleocr가 modelscope 경유로 끌어오는 torch 차단)
  paddle만 cuDNN을 로드한다.
- 결과적으로 **둘 다 GPU** 사용 가능. 별도 설정 불필요.

디바이스: 검출은 CUDA 자동, 인식은 `REC_DEVICE`(빈 값=자동 GPU, 강제 시 `cpu`|`gpu`).

> ⚠️ paddlepaddle/scipy 휠은 numpy 1.x로 빌드된 경우가 많다. numpy 2.x가 설치돼 있으면
> `numpy.core.multiarray failed to import`가 나므로 `numpy<2`로 맞출 것(requirements-local.txt).

자체 점검:
```
python -m backend.labels      # 파일 IO
python -m backend.projects    # 프로젝트·폴더 CRUD + 드래그 이동
python -m backend.keylist     # KEY 리스트 시드 + CRUD
python -m backend.llm         # 파싱/변환
python -m backend.pipeline <image_path>   # 로컬 파이프라인 (모델·deps 필요)
```
