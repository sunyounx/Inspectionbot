# README #

This README would normally document whatever steps are necessary to get your application up and running.

### What is this repository for? ###

* Quick summary
* Version
* [Learn Markdown](https://bitbucket.org/tutorials/markdowndemo)

### How do I get set up? ###

* Summary of set up
* Configuration
  * `NOTION_API_TOKEN`: Notion integration secret (`secret_...`). [Notion integrations](https://www.notion.so/myintegrations)에서 생성.
  * 승인(히스토리 적재) 시 Notion 링크는 **공식 API만** 사용합니다. 해당 **페이지를 integration에 공유**해야 합니다. 미공유·권한 오류 시 승인이 실패합니다. (링크 공개만으로는 읽을 수 없습니다.)
  * Notion database 동기화, 댓글, 첨부파일 다운로드는 1차 범위에서 제외됩니다.
  * Google 문서 링크는 기존과 같이 관리자 Google Drive OAuth 로그인이 필요합니다.
* Dependencies
* Database configuration
  * 앱 스키마 기준 파일: `db/schema.sql` + 배포 시 `init_db()`의 `ALTER ... IF NOT EXISTS`
  * **Replit**: 마이그레이션은 배포 시 **개발 DB ↔ 프로덕션 DB** 구조 diff로 자동 생성됨 (`db/schema.sql`을 직접 읽지 않음)
  * Replit에서 `DROP approved_history_id` 경고가 나오면 **적용하지 말 것** (승인 취소 기능에 필요)
  * 근본 해결 — **개발 DB**와 Replit 스키마 정의를 코드와 맞추기:
    1. Database → **Development** → SQL에서 실행:
       ```sql
       ALTER TABLE pending_approvals
         ADD COLUMN IF NOT EXISTS approved_history_id INTEGER;
       ```
    2. Database → Schema / Tables → `pending_approvals`에 컬럼 추가:
       - 이름: `approved_history_id`
       - 타입: `INTEGER`
       - nullable 허용 (NOT NULL 아님)
    3. Deploy 후 마이그레이션에 `DROP approved_history_id`가 없는지 확인
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
