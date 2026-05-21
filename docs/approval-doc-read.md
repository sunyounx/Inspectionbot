# 승인 시 문서 읽기 + Gemini 파이프라인

## 1. `update_pending_approved` (필수)

성공 시 **한 함수만** 사용한다. `status`와 `approved_history_id`를 같이 갱신한다.

```python
update_pending_approved(pending_id, history_id)
```

| 시점 | 함수 |
|------|------|
| bg 작업 시작 | `update_pending_status(id, "처리중")` |
| refine + insert 성공 | `update_pending_approved(id, history_id)` |
| 실패 롤백 | `update_pending_status(id, "대기중")` |

`update_pending_status(id, "승인됨")`만 호출하면 **승인 취소·되돌리기**가 `approved_history_id` 없이 깨진다. DB: `db/database.py` `update_pending_approved`.

## 2. `_insert_refined_history` — `access_token` 없음

문서 읽기는 **항상** 호출부에서 `_resolve_doc_content(pending, access_token)`로 먼저 수행한다.

```python
doc_content = await _resolve_doc_content(row, access_token)  # GEMINI_SEMAPHORE 밖
async with GEMINI_SEMAPHORE:
    history_id = await _insert_refined_history(
        row,
        doc_content=doc_content,
        category_override=...,
    )
```

`_insert_refined_history`는 `refine_with_document(full_text, doc_content)` + `insert_history`만 담당한다. Google OAuth 토큰은 `_resolve_doc_content` / `_ensure_token_for_docs`에만 있다.

## 3. `GEMINI_SEMAPHORE` 분리 (Phase A 필수)

Playwright·Google Drive·Notion API는 I/O bound이고 Gemini 슬롯을 점유하면 안 된다. **Notion Playwright(Phase B) 추가 전에** 아래 분리를 완료해야 한다.

- **밖**: `_resolve_doc_content` (Google thread, Notion API, Playwright fallback)
- **안**: `_insert_refined_history` → `refine_with_document`

분리를 “선택”으로 두고 Playwright를 세마포어 안에 넣으면 동시 승인 시 Gemini 슬롯이 문서 I/O에 묶인다.
