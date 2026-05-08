# 올더뮤 검수봇 v3 — 작업 지시서

## 절대 슬랙에 메시지는 보내지 말 것.

## AI 엔진: Google Gemini API
- SDK: `google-genai` (새 통합 SDK)
- 모델: `gemini-2.5-pro` (비용 효율 + 빠른 응답)
- 구조화 출력: `response_mime_type="application/json"` + `response_schema` 파라미터
- Vision: 이미지 입력 기본 지원 (`Part.from_data()`)

## Slack 연동 원칙
- **User OAuth Token** 사용 (봇이 아닌 사용자 권한으로 메시지 읽기)
- 광고주에게 봇 존재가 노출되지 않음 (앱 설치/봇 표시 없음)
- Replit 서버에서 **N분마다 폴링** (`conversations.history` API)
- Slack에 아무것도 보내지 않음 — 읽기 전용
- 승인/충돌 처리는 **웹앱 관리 화면**에서 진행

## 역할 분담
- **시니어 (Claude)**: 계획 수립 + 코드 리뷰
- **주니어 (본인)**: 코드 작성 → 완성 후 리뷰 요청

## 작업 방식
1. 아래 태스크를 순서대로 진행
2. 각 태스크 완료 시 코드를 보여주면 시니어가 리뷰
3. 리뷰 통과 → 다음 태스크로 이동

---

## 프로젝트 구조 (최종 목표)

```
inspection-bot/
├── main.py                      # FastAPI 엔트리포인트
├── requirements.txt
├── .env
├── .gitignore
├── tests/                       # API 테스트 스크립트
│   ├── test_gemini_classify.py
│   ├── test_gemini_refine.py
│   ├── test_gemini_conflict.py
│   ├── test_gemini_inspect.py
│   └── test_slack_poll.py           # Slack 폴링 테스트
├── db/
│   ├── schema.sql
│   └── database.py
├── services/
│   ├── gemini_service.py
│   └── slack_service.py         # Slack 폴링 (User OAuth Token)
├── routers/
│   ├── approval.py              # GET/POST /api/approval (웹앱 승인)
│   ├── history.py
│   └── inspect.py
├── prompts/
│   ├── classify.py
│   ├── refine.py
│   ├── conflict.py
│   └── inspect.py
├── models/
│   └── schemas.py
└── static/
    ├── index.html
    ├── style.css
    └── app.js
```

---

## Phase 0: API 테스트 (로직 구현 전에 먼저)

### Task 0-1: 환경 세팅
**만들 파일:** `requirements.txt`, `.env`, `.gitignore`

**requirements.txt 내용:**
```
google-genai
fastapi
uvicorn[standard]
python-dotenv
slack-sdk
python-multipart
aiofiles
```

**.env 내용 (본인 키로 채우기):**
```
GEMINI_API_KEY=AIza...
SLACK_USER_TOKEN=xoxp-...
SLACK_CHANNEL_ID=C0...
POLL_INTERVAL_MINUTES=3
```
> User OAuth Token(`xoxp-`) 사용. Bot Token(`xoxb-`) 아님!
> Slack 앱 설정 → OAuth & Permissions → User Token Scopes에 `channels:history`, `channels:read` 추가 필요

**.gitignore:** `.env`, `__pycache__/`, `*.db` 추가

**완료 후:** `pip install -r requirements.txt` 실행해서 에러 없는지 확인

---

### Task 0-2: Gemini API — 피드백 분류 테스트
**만들 파일:** `tests/test_gemini_classify.py`

**해야 할 것:**
1. `google.genai` 클라이언트 초기화 (`.env`에서 키 로드, `python-dotenv` 사용)
2. 시스템 프롬프트 작성: "이 슬랙 메시지가 광고 소재 관련 가이드라인/피드백/방향성인지 판별해"
3. 응답 형식: JSON `{"is_feedback": bool, "confidence": 0.0~1.0, "reason": "판별 근거"}`
4. 테스트 샘플 최소 4개:
   - 명확한 피드백: `"앞으로 배경에 퍼플 톤 비중을 30% 이상으로 올려주세요"`
   - 일반 대화: `"다음 미팅 언제예요?"`
   - 애매한 메시지: `"이번 소재 괜찮은 것 같아요"`
   - 이모지만: `"👍"`
5. 각 샘플에 대해 API 호출 → 결과 출력

**사용할 API:**
```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-2.5-pro",
    contents=user_message,
    config=types.GenerateContentConfig(
        system_instruction="시스템 프롬프트 여기에",
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "is_feedback": {"type": "boolean"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"}
            },
            "required": ["is_feedback", "confidence", "reason"]
        }
    )
)
result = json.loads(response.text)
```

**완료 기준:** `python tests/test_gemini_classify.py` 실행 시 4개 샘플 모두 합리적인 분류 결과 출력

---

### Task 0-3: Gemini API — 피드백 정제 테스트
**만들 파일:** `tests/test_gemini_refine.py`

**해야 할 것:**
1. 피드백 원문을 받아서 구조화된 데이터로 정제
2. 출력 필드:
   - `date`: 피드백 날짜 (없으면 오늘 날짜)
   - `topic`: 주제 키워드 1~3단어 (예: "퍼플 비중", "배경 톤")
   - `summary`: 1~2줄 요약
   - `scope`: "영상" / "이미지DA" / "카피" / "전체" 중 택1
   - `type`: "방향성" / "규칙" 중 택1
   - `original_quote`: 원문 그대로 발췌
3. 테스트 샘플 최소 3개 (다양한 길이/복잡도)

**사용할 API:** `response_mime_type="application/json"` + `response_schema`로 구조화 출력
```python
response = client.models.generate_content(
    model="gemini-2.5-pro",
    contents=raw_feedback_text,
    config=types.GenerateContentConfig(
        system_instruction="피드백 정제 프롬프트",
        response_mime_type="application/json",
        response_schema={
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "topic": {"type": "string"},
                "summary": {"type": "string"},
                "scope": {"type": "string", "enum": ["영상", "이미지DA", "카피", "전체"]},
                "type": {"type": "string", "enum": ["방향성", "규칙"]},
                "original_quote": {"type": "string"}
            },
            "required": ["date", "topic", "summary", "scope", "type", "original_quote"]
        }
    )
)
```

**완료 기준:** 3개 샘플 모두 valid한 구조화 데이터 출력. topic이 간결하고, original_quote가 원문 보존되는지 확인

---

### Task 0-4: Gemini API — 충돌 감지 테스트
**만들 파일:** `tests/test_gemini_conflict.py`

**해야 할 것:**
1. 기존 히스토리 1건 + 신규 피드백 1건을 Gemini에게 주고 충돌 여부 판별
2. 출력: `{"conflicts": bool, "explanation": "이유", "recommendation": "replace_old" | "keep_both" | "keep_old"}`
3. 테스트 쌍 2개:
   - 충돌: 기존 `"키위포 제외"` vs 신규 `"키위포 서브로 노출"`
   - 비충돌: 기존 `"헤더 볼드체"` vs 신규 `"본문 세리프체"`

**완료 기준:** 충돌 쌍은 `conflicts=true`, 비충돌 쌍은 `conflicts=false`

---

### Task 0-5: Gemini API — 검수 테스트
**만들 파일:** `tests/test_gemini_inspect.py`

**해야 할 것:**
1. 시스템 프롬프트에 샘플 히스토리 3~5개를 하드코딩으로 넣기
2. 사용자 메시지로 카피 텍스트 보내서 검수 요청
3. (선택) 테스트 이미지 1장으로 Vision 테스트
4. 검수 결과가 히스토리 규칙을 참조하는지 확인

**이미지 포함 호출 예시:**
```python
from google.genai import types

# 이미지 파일 읽기
with open("test_image.png", "rb") as f:
    image_data = f.read()

response = client.models.generate_content(
    model="gemini-2.5-pro",
    contents=[
        types.Part.from_data(data=image_data, mime_type="image/png"),
        "이 광고 소재를 검수해주세요."
    ],
    config=types.GenerateContentConfig(
        system_instruction="검수 시스템 프롬프트 + 히스토리 규칙"
    )
)
```

**시스템 프롬프트 예시 구조:**
```
당신은 광고 소재 검수봇입니다.
아래 히스토리 규칙을 기준으로 소재를 검수하세요.

## 활성 히스토리
1. [퍼플 비중] 배경에 퍼플 톤 30% 이상 (적용: 이미지DA)
2. [키위포] 키위포 서브 노출 (적용: 전체)
...

각 규칙에 대해 준수/위반/해당없음을 판정하고, 구체적 피드백을 제공하세요.
```

**완료 기준:** 검수 응답이 히스토리 규칙 번호를 인용하며 구체적 피드백 제공

---

### Task 0-6: Slack API — 폴링 테스트 (User OAuth Token)
**만들 파일:** `tests/test_slack_poll.py`

**해야 할 것:**
1. `slack_sdk.WebClient`를 **User OAuth Token**(`xoxp-`)으로 초기화
2. `conversations.history` API로 지정 채널의 최근 메시지 가져오기
3. 마지막으로 읽은 시점(`oldest` 파라미터) 이후 메시지만 가져오기

**핵심 코드:**
```python
from slack_sdk import WebClient
import os, time
from dotenv import load_dotenv

load_dotenv()
client = WebClient(token=os.getenv("SLACK_USER_TOKEN"))

# 최근 10분간 메시지 가져오기
oldest = str(time.time() - 600)
response = client.conversations_history(
    channel=os.getenv("SLACK_CHANNEL_ID"),
    oldest=oldest,
    limit=20
)

for msg in response["messages"]:
    print(f"[{msg.get('user', 'unknown')}] {msg.get('text', '')}")
    print(f"  ts: {msg['ts']}")
    print()
```

**테스트 방법:**
1. 슬랙 채널에 테스트 메시지 몇 개 보내기
2. `python tests/test_slack_poll.py` 실행
3. 메시지 내용 + timestamp 출력 확인

**완료 기준:** 채널의 최근 메시지가 정상적으로 조회됨. 봇 표시 없이 사용자 권한으로 읽기 확인

---

## Phase 1: 백엔드 기반

> Phase 0 완료 후 진행. Phase 0에서 만든 프롬프트/API 호출 코드를 모듈화하는 단계.

### Task 1-1: DB 스키마 + CRUD
**만들 파일:** `db/schema.sql`, `db/database.py`

**schema.sql — 테이블 3개:**

```sql
-- history 테이블
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    scope TEXT NOT NULL,          -- 영상 / 이미지DA / 카피 / 전체
    type TEXT NOT NULL,           -- 방향성 / 규칙
    original_quote TEXT,
    status TEXT NOT NULL DEFAULT '활성',  -- 활성 / 변경됨 / 폐기
    changed_date TEXT,
    slack_link TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- guideline 테이블
CREATE TABLE IF NOT EXISTS guideline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- terms 테이블
CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL,
    source TEXT
);
```

**database.py — 필요한 함수:**
- `init_db()` → schema.sql 읽어서 실행
- `get_active_history()` → `SELECT * FROM history WHERE status = '활성'`
- `get_history_by_topic(topic: str)` → topic으로 검색 (충돌 감지용)
- `insert_history(item: dict) -> int` → INSERT 후 lastrowid 반환
- `update_history_status(id: int, status: str, changed_date: str)` → UPDATE
- `get_guidelines()` → 전체 조회
- `get_terms()` → 전체 조회

**DB 파일 경로:** 프로젝트 루트의 `inspection_bot.db`

**완료 기준:** `python -c "from db.database import init_db; init_db()"` 에러 없이 실행, DB 파일 생성 확인

---

### Task 1-2: Pydantic 모델
**만들 파일:** `models/schemas.py`

**정의할 모델:**
```python
from pydantic import BaseModel
from typing import Literal, Optional

class FeedbackClassification(BaseModel):
    is_feedback: bool
    confidence: float
    reason: str

class RefinedFeedback(BaseModel):
    date: str
    topic: str
    summary: str
    scope: Literal["영상", "이미지DA", "카피", "전체"]
    type: Literal["방향성", "규칙"]
    original_quote: str

class ConflictCheck(BaseModel):
    conflicts: bool
    explanation: str
    recommendation: Literal["replace_old", "keep_both", "keep_old"]

class HistoryItem(BaseModel):
    id: Optional[int] = None
    date: str
    topic: str
    summary: str
    scope: str
    type: str
    original_quote: Optional[str] = None
    status: str = "활성"
    changed_date: Optional[str] = None
    slack_link: Optional[str] = None

class InspectRequest(BaseModel):
    message: str
    image_base64: Optional[str] = None
    image_media_type: Optional[str] = None
    mode: Literal["소재검수", "히스토리조회", "용어해석"] = "소재검수"

class InspectResponse(BaseModel):
    feedback: str
    rules_checked: int
```

**완료 기준:** import 에러 없이 모델 생성 가능

---

### Task 1-3: 프롬프트 모듈화
**만들 파일:** `prompts/classify.py`, `prompts/refine.py`, `prompts/conflict.py`, `prompts/inspect.py`

**각 파일 구조:**
```python
SYSTEM_PROMPT = """..."""  # Phase 0에서 테스트한 프롬프트

def build_messages(...) -> list[dict]:
    """Gemini API에 보낼 contents 배열 생성"""
    ...
```

**`prompts/inspect.py`만 특별:** 히스토리/가이드라인/용어를 받아서 시스템 프롬프트에 주입
```python
def build_system_prompt(history: list, guidelines: list, terms: list) -> str:
    """DB 데이터를 시스템 프롬프트에 포맷팅해서 합치기"""
    ...
```

**완료 기준:** Phase 0 테스트 스크립트에서 프롬프트를 이 모듈로 교체해도 동일하게 동작

---

### Task 1-4: Gemini 서비스
**만들 파일:** `services/gemini_service.py`

**Phase 0 테스트 코드에서 API 호출 부분을 함수로 추출:**
1. `classify_feedback(text: str) -> FeedbackClassification`
2. `refine_feedback(text: str) -> RefinedFeedback`
3. `check_conflict(new_item: dict, existing_item: dict) -> ConflictCheck`
4. `inspect_creative(system_prompt: str, contents: list) -> str`

- 클라이언트는 모듈 레벨에서 1번만 초기화: `client = genai.Client(api_key=...)`
- 모델: `gemini-2.5-pro`
- 구조화 출력: `response_mime_type="application/json"` + `response_schema`
- `prompts/` 모듈의 프롬프트 사용

**완료 기준:** 각 함수를 직접 호출해서 Phase 0과 동일한 결과 확인

---

### Task 1-5: Slack 폴링 서비스
**만들 파일:** `services/slack_service.py`

**User OAuth Token으로 채널 메시지를 폴링:**
- `fetch_new_messages(since_ts: str) -> list[dict]` → `conversations.history`로 `oldest=since_ts` 이후 메시지 조회
- `build_slack_link(channel: str, ts: str) -> str` → 원본 메시지 링크 생성
- 마지막 폴링 시점(`last_poll_ts`)은 DB 또는 파일에 저장하여 서버 재시작에도 유지

**폴링 스케줄러:** `main.py`에서 백그라운드 태스크로 N분마다 실행
```python
# main.py 스타트업에서 스케줄러 등록 (asyncio 또는 apscheduler 사용)
async def poll_slack():
    messages = fetch_new_messages(last_poll_ts)
    for msg in messages:
        # classify → refine → conflict check → pending_approvals에 저장
        ...
```

**완료 기준:** 서버 실행 시 N분마다 자동으로 새 메시지 조회 확인

---

### Task 1-6: FastAPI 앱 뼈대
**만들 파일:** `main.py` (기존 것 교체)

**내용:**
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from db.database import init_db

app = FastAPI(title="올더뮤 검수봇 v3")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    init_db()

# 라우터는 Phase 2, 3에서 추가
# app.include_router(...)

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**완료 기준:** `python main.py` → `http://localhost:8000/docs` 접속 시 Swagger UI 표시

---

## Phase 2: 슬랙 폴링 + 웹앱 승인

### Task 2-1: 폴링 스케줄러
**수정할 파일:** `main.py`, `services/slack_service.py`

**폴링 루프 구현:**
1. 서버 시작 시 백그라운드 태스크로 폴링 루프 시작
2. N분(`POLL_INTERVAL_MINUTES`)마다 `fetch_new_messages()` 호출
3. 각 메시지에 대해:
   - `classify_feedback(text)` → 피드백 아니면 스킵
   - `refine_feedback(text)` → 구조화
   - `get_history_by_topic(topic)` → 기존 히스토리 확인
   - 충돌 있으면 → `check_conflict()` 호출
   - **결과를 `pending_approvals` DB 테이블에 저장** (status: "대기중")
4. `last_poll_ts` 업데이트 (DB에 저장)

**구현 방식 (asyncio):**
```python
import asyncio

async def poll_slack_loop():
    while True:
        try:
            await poll_and_process()
        except Exception as e:
            print(f"폴링 에러: {e}")
        await asyncio.sleep(int(os.getenv("POLL_INTERVAL_MINUTES", 3)) * 60)

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(poll_slack_loop())
```

**완료 기준:** 슬랙 채널에 피드백 메시지 작성 → N분 후 `pending_approvals` DB에 정제 결과 자동 저장

---

### Task 2-2: 웹앱 승인 API
**만들 파일:** `routers/approval.py`

**엔드포인트 3개:**

`GET /api/approvals` → 대기중인 승인 목록 조회
- 정제된 피드백, 충돌 여부, 원문 발췌 등 표시
- status="대기중"인 항목만

`POST /api/approvals/{id}/approve` → 승인 (적재)
- `insert_history()` 호출
- pending 상태 → "승인됨"

`POST /api/approvals/{id}/reject` → 폐기
- pending 상태 → "폐기됨"

`POST /api/approvals/{id}/conflict` → 충돌 해결
- body: `{"action": "use_new" | "keep_old" | "keep_both"}`
- `use_new` → 기존 `update_history_status("변경됨")` + 신규 적재
- `keep_old` → pending 폐기
- `keep_both` → 신규 적재 (기존 유지)

**main.py에 추가:** `app.include_router(approval.router)`

**완료 기준:** 웹앱에서 승인 목록 조회 + 승인/폐기/충돌 해결 동작 확인

---

### DB 추가: pending_approvals 테이블 (Task 1-1 schema.sql에 추가)
```sql
CREATE TABLE IF NOT EXISTS pending_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    scope TEXT NOT NULL,
    type TEXT NOT NULL,
    original_quote TEXT,
    slack_link TEXT,
    has_conflict INTEGER NOT NULL DEFAULT 0,  -- 0: 없음, 1: 있음
    conflict_explanation TEXT,
    conflict_recommendation TEXT,
    conflict_old_history_id INTEGER,           -- 충돌 대상 기존 히스토리 ID
    status TEXT NOT NULL DEFAULT '대기중',      -- 대기중 / 승인됨 / 폐기됨
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## Phase 3: 웹앱

### Task 3-1: 검수 API
**만들 파일:** `routers/inspect.py`

**엔드포인트:** `POST /api/inspect`

**동작:**
1. `InspectRequest` 수신
2. DB에서 `get_active_history()`, `get_guidelines()`, `get_terms()` 조회
3. `build_system_prompt(history, guidelines, terms)` 호출
4. `build_messages(request.message, request.image_base64, request.image_media_type)` 호출
5. `inspect_creative(system_prompt, messages)` 호출
6. `InspectResponse` 반환

**main.py에 추가:** `app.include_router(inspect.router)`

**완료 기준:** curl/Postman으로 `/api/inspect` 호출 → 검수 피드백 반환

---

### Task 3-2: 히스토리 API
**만들 파일:** `routers/history.py`

**엔드포인트 3개:**
- `GET /api/history?status=활성` → 히스토리 목록 조회
- `POST /api/history` → 수동 히스토리 추가 (슬랙 외 채널 대응)
- `PATCH /api/history/{id}` → 상태 변경

**완료 기준:** 각 엔드포인트 curl로 테스트 통과

---

### Task 3-3: 프론트엔드
**만들 파일:** `static/index.html`, `static/style.css`, `static/app.js`

**UI 구성:**
1. **상단:** 모드 선택 버튼 3개
   - [🔍 소재 검수] [📂 히스토리 조회] [📖 용어 해석]
2. **중앙:** 채팅 영역 (스크롤)
   - 사용자 메시지 버블 (오른쪽)
   - 봇 응답 버블 (왼쪽)
3. **하단:** 입력 영역
   - 텍스트 입력 필드
   - 이미지 업로드 버튼 (📎)
   - 전송 버튼

**app.js 핵심 로직:**
- 이미지 선택 → `FileReader`로 base64 변환 → 미리보기 표시
- 전송 클릭 → `fetch("/api/inspect", {method: "POST", body: JSON.stringify(...)})` 
- 응답 수신 → 봇 메시지 버블 추가
- 로딩 중 표시 (Gemini API 응답 대기)

**완료 기준:** 브라우저에서 텍스트/이미지 업로드 → 검수 피드백 채팅으로 표시

---

### Task 3-4: 승인 관리 화면
**만들 파일:** `static/admin.html`, `static/admin.js` (또는 index.html에 탭으로 통합)

**UI 구성:**
1. 대기중인 피드백 카드 목록
   - 각 카드: topic, summary, scope, type, original_quote, 감지 시각 표시
   - 충돌 없는 경우: [승인] [폐기] 버튼
   - 충돌 있는 경우: 기존 히스토리 비교 표시 + [신규로 교체] [기존 유지] [둘 다 병기] 버튼
2. 처리 완료 시 카드가 목록에서 사라지거나 상태 표시 변경

**app.js(또는 admin.js) 핵심 로직:**
- `fetch("/api/approvals")` → 대기 목록 렌더링
- 버튼 클릭 → `fetch("/api/approvals/{id}/approve")` 등 호출 → 목록 갱신
- 자동 새로고침 (30초 폴링 or 수동 새로고침 버튼)

**완료 기준:** 슬랙에서 피드백 감지 → 웹앱 승인 화면에 카드 표시 → 승인 클릭 → DB 적재

---

## Phase 4: 통합 테스트

### 테스트 시나리오 목록

**슬랙 폴링 → 웹앱 승인 플로우:**
1. ✅ 채널에 피드백 메시지 → N분 후 폴링으로 감지 → pending_approvals DB에 저장
2. ✅ 슬랙에 봇 흔적 없음 (광고주 모름)
3. ✅ 웹앱 승인 화면에 대기 카드 표시
4. ✅ 승인 클릭 → DB history 테이블에 데이터 적재
5. ✅ 동일 topic 피드백 → 충돌 감지 → 웹앱에서 A/B/C 선택지 표시
6. ✅ 각 선택지 클릭 → 올바른 DB 상태 변경

**웹앱 플로우:**
5. ✅ 텍스트만 → 카피 검수 피드백
6. ✅ 이미지+텍스트 → 비주얼+카피 검수 피드백
7. ✅ 새 히스토리 적재 후 재검수 → 새 규칙 반영 확인
8. ✅ 히스토리 조회 모드 → DB 검색 결과 반환

**엣지 케이스:**
9. 일반 대화 메시지 → 분류에서 걸러져서 pending에 안 들어감
10. 빈 메시지 / 이모지만 → 무시
11. 히스토리 0건 상태에서 검수 → 정상 동작 (일반 피드백만)
12. 서버 재시작 후에도 last_poll_ts 유지 → 중복 처리 없음

---

## 핵심 주의사항

| 항목 | 내용 |
|------|------|
| AI 엔진 | Google Gemini API (`google-genai` SDK) |
| 모델 | `gemini-2.5-pro` 전부 통일 |
| 구조화 출력 | `response_mime_type="application/json"` + `response_schema` (분류/정제/충돌) |
| Slack 연동 | **User OAuth Token**(`xoxp-`) + 폴링 방식. 봇 없음, 광고주 노출 없음 |
| 폴링 주기 | `.env`의 `POLL_INTERVAL_MINUTES`로 설정 (기본 3분) |
| 승인 처리 | 슬랙이 아닌 **웹앱 관리 화면**에서 승인/폐기/충돌 해결 |
| pending 상태 | `pending_approvals` DB 테이블 사용 (서버 재시작에도 유지) |
| 한글 status | DB의 status 값은 한글 ("활성"/"변경됨"/"폐기") — 기획서 기준 |
| scope/type도 한글 | "영상"/"이미지DA"/"카피"/"전체", "방향성"/"규칙" |
