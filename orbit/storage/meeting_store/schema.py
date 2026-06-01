from __future__ import annotations


MEETING_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION orbit_jsonb_deep_merge(original JSONB, patch JSONB)
RETURNS JSONB
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    result JSONB := COALESCE(original, '{}'::jsonb);
    entry RECORD;
BEGIN
    IF jsonb_typeof(result) <> 'object' OR jsonb_typeof(COALESCE(patch, '{}'::jsonb)) <> 'object' THEN
        RETURN COALESCE(patch, result);
    END IF;

    FOR entry IN SELECT key, value FROM jsonb_each(COALESCE(patch, '{}'::jsonb))
    LOOP
        IF result ? entry.key
           AND jsonb_typeof(result -> entry.key) = 'object'
           AND jsonb_typeof(entry.value) = 'object' THEN
            result := jsonb_set(
                result,
                ARRAY[entry.key],
                orbit_jsonb_deep_merge(result -> entry.key, entry.value),
                true
            );
        ELSE
            result := jsonb_set(result, ARRAY[entry.key], entry.value, true);
        END IF;
    END LOOP;

    RETURN result;
END;
$$;

CREATE TABLE IF NOT EXISTS people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    phone TEXT,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    url TEXT,
    title TEXT,
    raw_text TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    gmeet_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    requested_by_person_id UUID REFERENCES people(id),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    summary_short TEXT,
    summary_long TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS capture_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    capture_strategy TEXT NOT NULL DEFAULT 'chrome_extension',
    stt_provider TEXT DEFAULT 'deepgram',
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN (
            'scheduled',
            'starting',
            'joining',
            'live',
            'streaming_audio',
            'processing',
            'processed',
            'failed'
        )),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    error_code TEXT,
    error_message TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_capture_sessions_meeting_id
    ON capture_sessions(meeting_id, created_at DESC);

CREATE TABLE IF NOT EXISTS source_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    speaker_label TEXT,
    speaker_person_id UUID REFERENCES people(id),
    start_ms INTEGER,
    end_ms INTEGER,
    text TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_chunks_source_id
    ON source_chunks(source_id, chunk_index);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
    run_type TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    output_json JSONB,
    status TEXT DEFAULT 'success',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    title TEXT,
    decision_text TEXT NOT NULL,
    rationale TEXT,
    owner_text TEXT,
    confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_decisions_meeting_id
    ON decisions (meeting_id, created_at DESC);

CREATE TABLE IF NOT EXISTS action_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    owner_text TEXT,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_action_items_meeting_id
    ON action_items (meeting_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance TEXT NOT NULL DEFAULT 'medium',
    confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memories_meeting_id
    ON memories (meeting_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_type
    ON memories (memory_type);
"""

