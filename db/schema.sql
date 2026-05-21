-- PostgreSQL schema (Replit DATABASE_URL)

CREATE TABLE IF NOT EXISTS history (
    id SERIAL PRIMARY KEY,
    date TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    scope TEXT NOT NULL,
    type TEXT NOT NULL,
    full_text TEXT,
    original_quote TEXT,
    source_ts TEXT,
    author_user_id TEXT,
    author_name TEXT,
    message_time TEXT,
    status TEXT NOT NULL DEFAULT '활성',
    changed_date TEXT,
    slack_link TEXT,
    category TEXT NOT NULL DEFAULT '미분류',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS guideline (
    id SERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS terms (
    id SERIAL PRIMARY KEY,
    term TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL,
    source TEXT
);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id SERIAL PRIMARY KEY,
    date TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    scope TEXT NOT NULL,
    type TEXT NOT NULL,
    full_text TEXT,
    original_quote TEXT,
    slack_link TEXT,
    source_ts TEXT,
    author_user_id TEXT,
    author_name TEXT,
    message_time TEXT,
    has_conflict INTEGER NOT NULL DEFAULT 0,
    conflict_explanation TEXT,
    conflict_recommendation TEXT,
    conflict_old_history_id INTEGER,
    approved_history_id INTEGER,
    -- status: 대기중 | 처리중(히스토리 적재 중) | 승인됨 | 폐기됨 | 흡수됨(스레드 댓글 pending으로 대체됨)
    status TEXT NOT NULL DEFAULT '대기중',
    category TEXT NOT NULL DEFAULT '크리에이티브',
    parent_ts TEXT,
    teams_notified INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS slack_raw_messages (
    id SERIAL PRIMARY KEY,
    ts TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    user_id TEXT,
    text TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    is_feedback INTEGER,
    slack_link TEXT,
    parent_ts TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS poll_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_files (
    id SERIAL PRIMARY KEY,
    message_ts TEXT NOT NULL,          -- slack_raw_messages.ts 참조
    file_id TEXT,                      -- 슬랙 파일 ID (없을 수 있음 - attachment/text URL의 경우)
    name TEXT,
    filetype TEXT,                     -- xlsx, png, pdf, google_docs, notion 등
    mimetype TEXT,
    url TEXT,
    is_external BOOLEAN DEFAULT FALSE,
    external_type TEXT,                -- google_docs, notion, figma 등
    size INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(message_ts, url)            -- 같은 메시지에 같은 URL 중복 방지
);

CREATE TABLE IF NOT EXISTS gdrive_inspections (
    id SERIAL PRIMARY KEY,
    folder_id TEXT NOT NULL,
    folder_name TEXT,
    file_names TEXT,
    image_ids TEXT,
    thumbnail_files TEXT,
    file_count INTEGER,
    feedback TEXT,
    rules_checked INTEGER,
    drive_url TEXT,
    notified_teams BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inspection_thumbnails (
    id SERIAL PRIMARY KEY,
    inspection_id INTEGER NOT NULL,
    image_index INTEGER NOT NULL,
    file_id TEXT,
    file_name TEXT,
    mime_type TEXT DEFAULT 'image/jpeg',
    image_data BYTEA NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(inspection_id, image_index)
);

CREATE TABLE IF NOT EXISTS slack_inspections (
    id SERIAL PRIMARY KEY,
    pending_approval_id INTEGER NOT NULL,
    original_text TEXT,
    feedback TEXT,
    rules_checked INTEGER,
    file_count INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS slack_inspection_thumbnails (
    id SERIAL PRIMARY KEY,
    slack_inspection_id INTEGER NOT NULL,
    image_index INTEGER NOT NULL,
    file_id TEXT,
    file_name TEXT,
    mime_type TEXT DEFAULT 'image/jpeg',
    image_data BYTEA NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(slack_inspection_id, image_index)
);

CREATE TABLE IF NOT EXISTS figma_inspections (
    id SERIAL PRIMARY KEY,
    file_key TEXT NOT NULL,
    file_name TEXT,
    node_id TEXT NOT NULL,
    figma_url TEXT,
    feedback TEXT,
    rules_checked INTEGER,
    file_count INTEGER DEFAULT 1,
    notified_teams BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS figma_inspection_thumbnails (
    id SERIAL PRIMARY KEY,
    figma_inspection_id INTEGER NOT NULL,
    image_index INTEGER NOT NULL,
    file_name TEXT,
    mime_type TEXT DEFAULT 'image/jpeg',
    image_data BYTEA NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(figma_inspection_id, image_index)
);

CREATE TABLE IF NOT EXISTS gdrive_saved_folders (
    id SERIAL PRIMARY KEY,
    folder_id TEXT NOT NULL UNIQUE,
    folder_name TEXT,
    drive_url TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gdrive_oauth_tokens (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at TIMESTAMP,
    user_email TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS figma_comment_images (
    id SERIAL PRIMARY KEY,
    file_key TEXT NOT NULL,
    comment_id TEXT NOT NULL,
    node_id TEXT,
    file_name TEXT,
    mime_type TEXT NOT NULL DEFAULT 'image/png',
    image_data BYTEA NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(file_key, comment_id)
);

CREATE TABLE IF NOT EXISTS copybank (
    id SERIAL PRIMARY KEY,
    category TEXT,
    target TEXT,
    copy_text TEXT NOT NULL,
    tags TEXT,
    source TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
