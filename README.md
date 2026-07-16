# OCR 라벨링 웹 도구

로컬 이미지 폴더의 OCR 라벨(박스 + 텍스트)을 브라우저에서 조회·수정하고,
LLM(GPT/Claude) 또는 로컬 모델로 라벨 초안을 생성한다.

기능·데이터 형식·구조 설명: [doc/OVERVIEW.md](doc/OVERVIEW.md)

## 사용 흐름
첫 화면에서 **프로젝트**(제목·설명·데이터 폴더)를 만들고 카드를 열면 라벨링 화면으로 진입.
프로젝트는 서버 `projects.json`에 저장된다.

## 백엔드 구조
```
backend/
  app.py          # 메인 (FastAPI 라우팅)
  config.py       # .env 로딩 + 프로바이더/모델 경로
  projects.py     # 프로젝트 CRUD (projects.json)
  labels.py       # 라벨 파일 IO
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

## 실행

### 백엔드
```
pip install -r requirements.txt
copy .env.example .env      # API 키 입력 (ANTHROPIC_API_KEY 또는 OPENAI_API_KEY + LLM_PROVIDER)
uvicorn backend.app:app --reload      # http://localhost:8000
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
python -m backend.llm         # 파싱/변환
python -m backend.pipeline <image_path>   # 로컬 파이프라인 (모델·deps 필요)
```
