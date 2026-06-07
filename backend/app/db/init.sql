-- ============================================================================
-- NovelScript (析幕) — Database Schema v2.0.0
-- PostgreSQL 18 — All-in-One Design
-- Idempotent: safe to run multiple times
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Extensions
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ----------------------------------------------------------------------------
-- Tables
-- ----------------------------------------------------------------------------

-- 0. users
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(150) NOT NULL,
    email           VARCHAR(320) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(200),
    avatar_url      TEXT,
    role            VARCHAR(10)  NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user')),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT uq_users_username UNIQUE (username),
    CONSTRAINT uq_users_email    UNIQUE (email)
);

-- 1. novels
CREATE TABLE IF NOT EXISTS novels (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    title       VARCHAR(500) NOT NULL,
    author      VARCHAR(300),
    source_text TEXT,
    word_count  INTEGER      NOT NULL DEFAULT 0,
    language    VARCHAR(5)   NOT NULL DEFAULT 'zh'
                    CHECK (language IN ('zh', 'en')),
    status      VARCHAR(20)  NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'processing', 'completed')),
    metadata    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 2. tasks
CREATE TABLE IF NOT EXISTS tasks (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id         UUID         NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    user_id          UUID         REFERENCES users(id) ON DELETE SET NULL,
    status           VARCHAR(30)  NOT NULL DEFAULT 'pending'
                         CHECK (status IN (
                             'pending','preprocessing','converting',
                             'completed','failed'
                         )),
    progress         INTEGER      NOT NULL DEFAULT 0
                         CHECK (progress >= 0 AND progress <= 100),
    summary          TEXT,
    characters_json  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    script_yaml      TEXT,
    script_json      JSONB,
    script_fountain  TEXT,
    error_message    TEXT,
    pipeline_config  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    token_usage      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 3. chapters
CREATE TABLE IF NOT EXISTS chapters (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id       UUID        NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    chapter_index  INTEGER     NOT NULL,
    title          VARCHAR(500),
    content        TEXT,
    embedding      vector(1536),
    metadata       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 4. knowledge_nodes
CREATE TABLE IF NOT EXISTS knowledge_nodes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id    UUID        NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    task_id     UUID        REFERENCES tasks(id) ON DELETE SET NULL,
    node_type   VARCHAR(20) NOT NULL
                    CHECK (node_type IN (
                        'character','location','item','organization',
                        'event','concept'
                    )),
    name        VARCHAR(300) NOT NULL,
    aliases     TEXT[]       NOT NULL DEFAULT '{}',
    description TEXT,
    properties  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    embedding   vector(1536),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 5. knowledge_edges
CREATE TABLE IF NOT EXISTS knowledge_edges (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id         UUID        NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    task_id          UUID        REFERENCES tasks(id) ON DELETE SET NULL,
    source_node_id   UUID        NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    target_node_id   UUID        NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    relation         VARCHAR(100) NOT NULL DEFAULT '',
    weight           FLOAT       NOT NULL DEFAULT 1.0,
    evidence         TEXT,
    metadata         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 6. operations
CREATE TABLE IF NOT EXISTS operations (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id            UUID        NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id            UUID        REFERENCES users(id) ON DELETE SET NULL,
    type               VARCHAR(20) NOT NULL
                           CHECK (type IN (
                               'manual_edit','ai_patch','snapshot','rollback'
                           )),
    target_path        TEXT,
    diff_json          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    previous_snapshot  JSONB,
    applied            BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7. dialogues
CREATE TABLE IF NOT EXISTS dialogues (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id     UUID        NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id     UUID        REFERENCES users(id) ON DELETE SET NULL,
    role        VARCHAR(10) NOT NULL
                    CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT        NOT NULL DEFAULT '',
    patch_json  JSONB       NOT NULL DEFAULT '{}'::jsonb,
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 8. audit_logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        REFERENCES users(id) ON DELETE SET NULL,
    task_id     UUID        REFERENCES tasks(id) ON DELETE SET NULL,
    level       VARCHAR(10) NOT NULL DEFAULT 'info'
                    CHECK (level IN ('debug','info','warn','error','fatal')),
    category    VARCHAR(100),
    message     TEXT        NOT NULL DEFAULT '',
    detail      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- Default Indexes (B-tree)
--   NOTE: email and username are already covered by UNIQUE constraints
--   (uq_users_email, uq_users_username) — no separate index needed.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_novels_user_id     ON novels(user_id);
CREATE INDEX IF NOT EXISTS idx_novels_status      ON novels(status);
CREATE INDEX IF NOT EXISTS idx_tasks_novel_id     ON tasks(novel_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user_id      ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status       ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_chapters_novel_id  ON chapters(novel_id);
CREATE INDEX IF NOT EXISTS idx_chapters_index     ON chapters(chapter_index);
CREATE INDEX IF NOT EXISTS idx_kn_nodes_novel_id  ON knowledge_nodes(novel_id);
CREATE INDEX IF NOT EXISTS idx_kn_nodes_task_id   ON knowledge_nodes(task_id);
CREATE INDEX IF NOT EXISTS idx_kn_nodes_type      ON knowledge_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_kn_edges_novel_id  ON knowledge_edges(novel_id);
CREATE INDEX IF NOT EXISTS idx_kn_edges_task_id   ON knowledge_edges(task_id);
CREATE INDEX IF NOT EXISTS idx_kn_edges_src       ON knowledge_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_kn_edges_tgt       ON knowledge_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_operations_task_id ON operations(task_id);
CREATE INDEX IF NOT EXISTS idx_operations_user_id ON operations(user_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_task_id  ON dialogues(task_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_user_id  ON dialogues(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_task_id ON audit_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_level   ON audit_logs(level);

-- ----------------------------------------------------------------------------
-- Vector Indexes (HNSW) for RAG — chapters & knowledge_nodes embeddings
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_chapters_embedding_hnsw
    ON chapters
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

CREATE INDEX IF NOT EXISTS idx_kn_nodes_embedding_hnsw
    ON knowledge_nodes
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- ----------------------------------------------------------------------------
-- Trigram Index for knowledge_nodes name fuzzy search
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_kn_nodes_name_trgm
    ON knowledge_nodes
    USING gin (name gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- Composite unique index on chapters (novel_id, chapter_index)
-- ----------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_chapters_novel_index
    ON chapters(novel_id, chapter_index);
