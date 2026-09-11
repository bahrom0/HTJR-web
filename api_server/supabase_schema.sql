-- ============================================================================
-- Tajik HTR Studio — Supabase PostgreSQL Schema & Storage Setup
-- Скопируйте и выполните этот SQL в Supabase SQL Editor:
-- https://supabase.com/dashboard/project/ingsfsksbzxfdfqkbjgi/sql/new
-- ============================================================================

-- 1. СЕССИИ (Анонимные сессии пользователей)
CREATE TABLE IF NOT EXISTS access_sessions (
    id TEXT PRIMARY KEY,
    token_hash BYTEA DEFAULT '\x00',
    csrf_hash BYTEA DEFAULT '\x00',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '10 years'),
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. ДОКУМЕНТЫ
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_session_id);

-- 3. АССЕТЫ (Файлы изображений и сканов)
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    storage_key TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size BIGINT NOT NULL DEFAULT 0,
    media_type TEXT NOT NULL DEFAULT 'image/png',
    state TEXT NOT NULL DEFAULT 'committed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    committed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    original_filename TEXT,
    kind TEXT DEFAULT 'original',
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_assets_owner ON assets(owner_session_id);
CREATE INDEX IF NOT EXISTS idx_assets_storage_key ON assets(storage_key);

-- 4. СТРАНИЦЫ
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    prepared_asset_id TEXT REFERENCES assets(id) ON DELETE SET NULL,
    page_index INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    preprocessing_recipe_hash TEXT,
    preparation_confirmed_recipe_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, page_index)
);
CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id);

-- 5. ИДЕМПОТЕНТНОСТЬ ЗАГРУЗОК
CREATE TABLE IF NOT EXISTS upload_idempotency (
    owner_session_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    document_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (owner_session_id, idempotency_key)
);

-- 6. ЗАДАЧИ РАСПОЗНАВАНИЯ (Jobs)
CREATE TABLE IF NOT EXISTS recognition_jobs (
    id TEXT PRIMARY KEY,
    owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'completed',
    stage TEXT DEFAULT 'completed',
    priority INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 1,
    max_attempts INTEGER DEFAULT 1,
    processed_count INTEGER DEFAULT 1,
    total_count INTEGER DEFAULT 1,
    cancellation_requested_at TIMESTAMPTZ,
    error_code TEXT,
    error_retryable BOOLEAN DEFAULT FALSE,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_rec_jobs_doc ON recognition_jobs(document_id);

-- 7. ЗАПУСКИ РАСПОЗНАВАНИЯ (Runs)
CREATE TABLE IF NOT EXISTS recognition_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL DEFAULT 1,
    model_manifest_sha256 TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    outcome TEXT DEFAULT 'succeeded',
    UNIQUE(job_id, attempt)
);

-- 8. РЕГИОНЫ ТЕКСТА НА СТРАНИЦЕ
CREATE TABLE IF NOT EXISTS recognition_regions (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    polygon_json TEXT NOT NULL,
    reading_order INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rec_regions_page ON recognition_regions(page_id);

-- 9. СТРОКИ ТЕКСТА
CREATE TABLE IF NOT EXISTS text_lines (
    id TEXT PRIMARY KEY,
    region_id TEXT NOT NULL REFERENCES recognition_regions(id) ON DELETE CASCADE,
    line_index INTEGER NOT NULL,
    bbox_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_text_lines_region ON text_lines(region_id);

-- 10. ВЕРСИИ ТЕКСТА (Сырой, распознанный, подтвержденный)
CREATE TABLE IF NOT EXISTS text_versions (
    id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL REFERENCES text_lines(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, -- 'raw', 'suggested', 'confirmed'
    text TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_text_versions_line ON text_versions(line_id);

-- 11. СЫРОЙ ТЕКСТ СТРАНИЦЫ
CREATE TABLE IF NOT EXISTS page_raw_results (
    id TEXT PRIMARY KEY,
    recognition_run_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    owner_session_id TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    is_partial BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_page_raw_results ON page_raw_results(page_id);

-- 12. ЧЕРНОВИКИ РЕДАКТОРА
CREATE TABLE IF NOT EXISTS editor_line_drafts (
    line_id TEXT NOT NULL,
    owner_session_id TEXT NOT NULL,
    text TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (line_id, owner_session_id)
);

-- 13. ИСПРАВЛЕНИЯ
CREATE TABLE IF NOT EXISTS corrections (
    id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL,
    from_version_id TEXT,
    to_version_id TEXT,
    owner_session_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- НАСТРОЙКА SUPABASE STORAGE (Бакет htr-uploads и доступ на чтение/запись)
-- ============================================================================

-- Создаем бакет htr-uploads как публичный, если его еще нет
INSERT INTO storage.buckets (id, name, public)
VALUES ('htr-uploads', 'htr-uploads', true)
ON CONFLICT (id) DO UPDATE SET public = true;

-- Политика: разрешить загрузку любых файлов в бакет htr-uploads
DROP POLICY IF EXISTS "Public Uploads in htr-uploads" ON storage.objects;
CREATE POLICY "Public Uploads in htr-uploads"
ON storage.objects
FOR INSERT
WITH CHECK (bucket_id = 'htr-uploads');

-- Политика: разрешить обновление/перезапись файлов в бакете htr-uploads
DROP POLICY IF EXISTS "Public Updates in htr-uploads" ON storage.objects;
CREATE POLICY "Public Updates in htr-uploads"
ON storage.objects
FOR UPDATE
USING (bucket_id = 'htr-uploads');

-- Политика: разрешить публичное чтение файлов из бакета htr-uploads
DROP POLICY IF EXISTS "Public Reads in htr-uploads" ON storage.objects;
CREATE POLICY "Public Reads in htr-uploads"
ON storage.objects
FOR SELECT
USING (bucket_id = 'htr-uploads');
