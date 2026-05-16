SQLITE_SCHEMA = (
    """
    create table if not exists generation_jobs (
      id text primary key,
      topic text not null,
      category text not null default 'Tech',
      audience text not null default 'curious tech listeners',
      target_duration_seconds integer not null default 600,
      language text not null default 'en',
      tone text not null default 'clear, smart, conversational',
      source_urls text not null default '[]',
      auto_publish integer not null default 0,
      status text not null default 'queued',
      current_step text,
      error text,
      metadata text not null default '{}',
      created_by text,
      created_at text not null default (CURRENT_TIMESTAMP),
      updated_at text not null default (CURRENT_TIMESTAMP),
      check (status in (
        'queued', 'running', 'awaiting_script_approval',
        'completed', 'failed', 'canceled'
      ))
    )
    """,
    """
    create table if not exists artifacts (
      id text primary key,
      job_id text references generation_jobs(id) on delete cascade,
      episode_id text,
      artifact_type text not null,
      r2_key text not null,
      mime_type text not null,
      size_bytes integer,
      checksum_sha256 text,
      metadata text not null default '{}',
      created_at text not null default (CURRENT_TIMESTAMP)
    )
    """,
    """
    create table if not exists agent_runs (
      id text primary key,
      job_id text not null references generation_jobs(id) on delete cascade,
      agent_name text not null,
      step text not null,
      status text not null default 'running',
      model text,
      input_artifact_id text references artifacts(id),
      output_artifact_id text references artifacts(id),
      usage text not null default '{}',
      error text,
      started_at text not null default (CURRENT_TIMESTAMP),
      completed_at text,
      check (status in ('running', 'completed', 'failed'))
    )
    """,
    """
    create table if not exists sources (
      id text primary key,
      job_id text not null references generation_jobs(id) on delete cascade,
      url text not null,
      title text,
      publisher text,
      author text,
      published_at text,
      retrieved_at text not null default (CURRENT_TIMESTAMP),
      source_tier text not null default 'B',
      credibility_score numeric,
      notes text,
      created_at text not null default (CURRENT_TIMESTAMP),
      unique (job_id, url)
    )
    """,
    """
    create table if not exists claims (
      id text primary key,
      job_id text not null references generation_jobs(id) on delete cascade,
      claim_text text not null,
      source_urls text not null default '[]',
      verification_status text not null default 'unverified',
      confidence numeric,
      notes text,
      used_in_script integer not null default 0,
      created_at text not null default (CURRENT_TIMESTAMP),
      updated_at text not null default (CURRENT_TIMESTAMP),
      check (verification_status in (
        'unverified', 'supported', 'unsupported', 'misleading', 'needs_context'
      ))
    )
    """,
    """
    create table if not exists episodes (
      id text primary key,
      generation_job_id text references generation_jobs(id) on delete set null,
      title text not null,
      slug text not null unique,
      category text not null default 'Tech',
      status text not null default 'draft',
      summary text,
      description text,
      duration_seconds integer,
      language text not null default 'en',
      metadata text not null default '{}',
      published_at text,
      created_at text not null default (CURRENT_TIMESTAMP),
      updated_at text not null default (CURRENT_TIMESTAMP),
      check (status in ('draft', 'published', 'archived'))
    )
    """,
    """
    create table if not exists episode_assets (
      id text primary key,
      episode_id text not null references episodes(id) on delete cascade,
      asset_type text not null,
      r2_key text not null,
      public_url text,
      mime_type text not null,
      size_bytes integer,
      checksum_sha256 text,
      metadata text not null default '{}',
      created_at text not null default (CURRENT_TIMESTAMP),
      unique (episode_id, asset_type)
    )
    """,
    """
    create table if not exists speakers (
      id text primary key,
      job_id text references generation_jobs(id) on delete cascade,
      episode_id text references episodes(id) on delete cascade,
      name text not null,
      role text,
      voice_name text not null,
      style text,
      created_at text not null default (CURRENT_TIMESTAMP)
    )
    """,
    """
    create table if not exists tts_segments (
      id text primary key,
      job_id text not null references generation_jobs(id) on delete cascade,
      segment_index integer not null,
      transcript text not null,
      r2_key text,
      mime_type text,
      duration_seconds numeric,
      status text not null default 'pending',
      error text,
      created_at text not null default (CURRENT_TIMESTAMP),
      updated_at text not null default (CURRENT_TIMESTAMP),
      unique (job_id, segment_index),
      check (status in ('pending', 'running', 'completed', 'failed'))
    )
    """,
    """
    create table if not exists queue_messages (
      id integer primary key autoincrement,
      queue_name text not null,
      message text not null,
      read_ct integer not null default 0,
      visible_at real not null,
      archived_at real,
      created_at real not null,
      updated_at real not null
    )
    """,
    """
    create table if not exists automation_locks (
      name text primary key,
      owner_id text not null,
      expires_at text not null,
      updated_at text not null default (CURRENT_TIMESTAMP)
    )
    """,
    "create index if not exists idx_generation_jobs_status on generation_jobs(status)",
    "create index if not exists idx_generation_jobs_created_at on generation_jobs(created_at desc)",
    "create index if not exists idx_agent_runs_job_id on agent_runs(job_id)",
    """
    create index if not exists idx_artifacts_job_id_type
    on artifacts(job_id, artifact_type, created_at desc)
    """,
    "create index if not exists idx_sources_job_id on sources(job_id)",
    "create index if not exists idx_claims_job_id on claims(job_id)",
    """
    create index if not exists idx_episodes_status_published_at
    on episodes(status, published_at desc)
    """,
    "create index if not exists idx_episode_assets_episode_id on episode_assets(episode_id)",
    """
    create index if not exists idx_queue_visible
    on queue_messages(queue_name, archived_at, visible_at, id)
    """,
)
