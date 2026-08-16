CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS video_vector_block (
    id SERIAL PRIMARY KEY,
    video_id VARCHAR(64) NOT NULL,
    block_type VARCHAR(32) NOT NULL,
    block_content TEXT NOT NULL,
    content_vector vector(384),
    block_weight INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (video_id, block_type)
);

CREATE INDEX IF NOT EXISTS idx_video_vector_block_video_id
    ON video_vector_block (video_id);

CREATE INDEX IF NOT EXISTS idx_video_vector_block_type
    ON video_vector_block (block_type);

CREATE TABLE IF NOT EXISTS platform_docs (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    type VARCHAR(50) DEFAULT 'faq',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- User long-term memory
CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    type VARCHAR(32) NOT NULL DEFAULT 'fact',
    content TEXT NOT NULL,
    source VARCHAR(32) DEFAULT 'inferred',
    score REAL DEFAULT 1.0,
    tags TEXT[] DEFAULT '{}',
    last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_memory_user_id
    ON user_memory (user_id);
CREATE INDEX IF NOT EXISTS idx_user_memory_type
    ON user_memory (type);
CREATE INDEX IF NOT EXISTS idx_user_memory_content_trgm
    ON user_memory USING gin (content gin_trgm_ops);

-- Chat history
-- 结构与 app/tools/db/schema.py 的 init_agent_tables() 保持一致。
-- 注意：代码只写入 user_id/question/answer/session_id/image_urls/videos/reasons，
-- 不写入 role/content/workflow_type。这些历史列保留但必须可空，避免 NOT NULL 导致插入失败。
CREATE TABLE IF NOT EXISTS chat_history (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64),
    user_id VARCHAR(64),
    role VARCHAR(16),
    content TEXT,
    question TEXT,
    answer TEXT,
    image_urls TEXT[] DEFAULT '{}',
    workflow_type VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    videos JSONB DEFAULT '[]',
    reasons JSONB DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_chat_history_session
    ON chat_history (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_user
    ON chat_history (user_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_created
    ON chat_history (created_at DESC);

-- Harness: workflow checkpoints（状态快照 + 断点恢复）
CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    id BIGSERIAL PRIMARY KEY,
    checkpoint_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    workflow_type VARCHAR(64) NOT NULL,
    step_name VARCHAR(64) NOT NULL,
    state_snapshot JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'completed',
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (session_id, workflow_type, step_name)
);

CREATE INDEX IF NOT EXISTS idx_checkpoint_session
    ON workflow_checkpoints (session_id);
CREATE INDEX IF NOT EXISTS idx_checkpoint_workflow
    ON workflow_checkpoints (session_id, workflow_type);
CREATE INDEX IF NOT EXISTS idx_checkpoint_created_at
    ON workflow_checkpoints (created_at DESC);

-- Harness: run artifacts（工具调用 trace + 事后复盘）
CREATE TABLE IF NOT EXISTS run_artifacts (
    id BIGSERIAL PRIMARY KEY,
    call_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    workflow_type VARCHAR(64) NOT NULL,
    artifact_type VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifact_session
    ON run_artifacts (session_id);
CREATE INDEX IF NOT EXISTS idx_artifact_type
    ON run_artifacts (artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifact_created_at
    ON run_artifacts (created_at DESC);
