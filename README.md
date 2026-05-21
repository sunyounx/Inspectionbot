# README #

This README would normally document whatever steps are necessary to get your application up and running.

### What is this repository for? ###

* Quick summary
* Version
* [Learn Markdown](https://bitbucket.org/tutorials/markdowndemo)

### How do I get set up? ###

* Summary of set up
* Configuration
  * **Notion OAuth** (권장): `NOTION_OAUTH_CLIENT_ID`, `NOTION_OAUTH_CLIENT_SECRET`, `NOTION_OAUTH_REDIRECT_URI` — 웹 UI에서 Notion 연결 후 페이지 피커로 접근 허용.
  * `NOTION_API_TOKEN`: (선택) OAuth 없을 때 internal integration fallback.
  * 읽기 순서: **Notion OAuth API** → 403/404 시 **Playwright** 자동 폴백. Replit build는 `playwright install` 실패해도 Deploy는 계속됨(실패 시 Shell에서 재설치).
  * Notion database 동기화, 댓글, 첨부파일 다운로드는 1차 범위에서 제외됩니다.
  * Google 문서 링크는 기존과 같이 관리자 Google Drive OAuth 로그인이 필요합니다.
  * 승인 파이프라인(`update_pending_approved`, `_resolve_doc_content`, `GEMINI_SEMAPHORE` 분리): [docs/approval-doc-read.md](docs/approval-doc-read.md)
* Dependencies
* Database configuration
  * 앱 스키마 기준 파일: `db/schema.sql` + 배포 시 `init_db()`의 `ALTER ... IF NOT EXISTS`
  * **Replit**: 마이그레이션은 배포 시 **개발 DB ↔ 프로덕션 DB** 구조 diff로 자동 생성됨 (`db/schema.sql`을 직접 읽지 않음)
  * Replit에서 `DROP approved_history_id` 또는 `DROP notion_oauth_tokens` 경고가 나오면 **Approve 하지 말 것**
  * 근본 해결 — **Development DB**에 코드와 맞는 구조를 먼저 만든 뒤 Deploy:
    1. Database → **Development** → **SQL** 탭에서 실행:
       ```sql
       ALTER TABLE pending_approvals
         ADD COLUMN IF NOT EXISTS approved_history_id INTEGER;

       CREATE TABLE IF NOT EXISTS notion_oauth_tokens (
         id SERIAL PRIMARY KEY,
         session_id TEXT NOT NULL UNIQUE,
         access_token TEXT NOT NULL,
         refresh_token TEXT,
         workspace_id TEXT,
         workspace_name TEXT,
         bot_id TEXT,
         owner_user_id TEXT,
         owner_email TEXT,
         created_at TIMESTAMP NOT NULL DEFAULT NOW()
       );
       ```
    2. (선택) Schema UI로 `notion_oauth_tokens` 테이블·`approved_history_id` 컬럼이 보이는지 확인
    3. Deploy 미리보기에서 마이그레이션에 **DROP** 이 없는지 확인 후 Publish
  * `DROP notion_oauth_tokens`를 적용하면 Notion OAuth 연결 정보가 전부 삭제되고 승인 시 Notion 읽기가 깨집니다.
  * **Shell에서 마이그레이션** (Database SQL 패널 대신):
    ```bash
    python scripts/db_migrate.py
    ```
    Replit Shell에서는 프로젝트 루트에서 실행. `DATABASE_URL`은 Secrets에 있어야 합니다.
  * SQL은 Repl **Shell**이 아니라 Database 패널의 **SQL/Query** 탭에서 실행 (Shell에 붙이면 `bash: ALTER: command not found`)
* How to run tests
* Deployment instructions

### Contribution guidelines ###

* Writing tests
* Code review
* Other guidelines

### Who do I talk to? ###

* Repo owner or admin
* Other community or team contact
