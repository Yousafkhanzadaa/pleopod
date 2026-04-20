create extension if not exists pgcrypto;
create extension if not exists pgmq;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists podcast_topics (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists generation_jobs (
  id uuid primary key default gen_random_uuid(),
  topic text not null,
  category text not null default 'Tech',
  audience text not null default 'curious tech listeners',
  target_duration_seconds integer not null default 600,
  language text not null default 'en',
  tone text not null default 'clear, smart, conversational',
  source_urls jsonb not null default '[]'::jsonb,
  auto_publish boolean not null default false,
  status text not null default 'queued',
  current_step text,
  error text,
  metadata jsonb not null default '{}'::jsonb,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint generation_jobs_status_check check (
    status in (
      'queued', 'running', 'awaiting_research_approval', 'awaiting_script_approval',
      'completed', 'failed', 'canceled'
    )
  )
);

create table if not exists artifacts (
  id uuid primary key default gen_random_uuid(),
  job_id uuid references generation_jobs(id) on delete cascade,
  episode_id uuid,
  artifact_type text not null,
  r2_key text not null,
  mime_type text not null,
  size_bytes bigint,
  checksum_sha256 text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists agent_runs (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references generation_jobs(id) on delete cascade,
  agent_name text not null,
  step text not null,
  status text not null default 'running',
  model text,
  input_artifact_id uuid references artifacts(id),
  output_artifact_id uuid references artifacts(id),
  usage jsonb not null default '{}'::jsonb,
  error text,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint agent_runs_status_check check (status in ('running', 'completed', 'failed'))
);

create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references generation_jobs(id) on delete cascade,
  url text not null,
  title text,
  publisher text,
  author text,
  published_at timestamptz,
  retrieved_at timestamptz not null default now(),
  source_tier text not null default 'B',
  credibility_score numeric(4,3),
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists claims (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references generation_jobs(id) on delete cascade,
  claim_text text not null,
  source_urls jsonb not null default '[]'::jsonb,
  verification_status text not null default 'unverified',
  confidence numeric(4,3),
  notes text,
  used_in_script boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint claims_verification_check check (
    verification_status in (
      'unverified', 'supported', 'unsupported', 'misleading', 'needs_context'
    )
  )
);

create table if not exists episodes (
  id uuid primary key default gen_random_uuid(),
  generation_job_id uuid references generation_jobs(id) on delete set null,
  title text not null,
  slug text not null unique,
  category text not null default 'Tech',
  status text not null default 'draft',
  summary text,
  description text,
  duration_seconds integer,
  language text not null default 'en',
  metadata jsonb not null default '{}'::jsonb,
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint episodes_status_check check (status in ('draft', 'published', 'archived'))
);

alter table artifacts
  drop constraint if exists artifacts_episode_id_fkey;

alter table artifacts
  add constraint artifacts_episode_id_fkey
  foreign key (episode_id) references episodes(id) on delete cascade;

create table if not exists episode_assets (
  id uuid primary key default gen_random_uuid(),
  episode_id uuid not null references episodes(id) on delete cascade,
  asset_type text not null,
  r2_key text not null,
  public_url text,
  mime_type text not null,
  size_bytes bigint,
  checksum_sha256 text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (episode_id, asset_type)
);

create table if not exists speakers (
  id uuid primary key default gen_random_uuid(),
  job_id uuid references generation_jobs(id) on delete cascade,
  episode_id uuid references episodes(id) on delete cascade,
  name text not null,
  role text,
  voice_name text not null,
  style text,
  created_at timestamptz not null default now()
);

create table if not exists tts_segments (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references generation_jobs(id) on delete cascade,
  segment_index integer not null,
  transcript text not null,
  r2_key text,
  mime_type text,
  duration_seconds numeric(10,3),
  status text not null default 'pending',
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (job_id, segment_index),
  constraint tts_segments_status_check check (status in ('pending', 'running', 'completed', 'failed'))
);

create index if not exists idx_generation_jobs_status on generation_jobs(status);
create index if not exists idx_generation_jobs_created_at on generation_jobs(created_at desc);
create index if not exists idx_agent_runs_job_id on agent_runs(job_id);
create index if not exists idx_artifacts_job_id_type on artifacts(job_id, artifact_type, created_at desc);
create index if not exists idx_sources_job_id on sources(job_id);
create index if not exists idx_claims_job_id on claims(job_id);
create index if not exists idx_episodes_status_published_at on episodes(status, published_at desc);
create index if not exists idx_episode_assets_episode_id on episode_assets(episode_id);

drop trigger if exists set_updated_at_podcast_topics on podcast_topics;
create trigger set_updated_at_podcast_topics
before update on podcast_topics
for each row execute function public.set_updated_at();

drop trigger if exists set_updated_at_generation_jobs on generation_jobs;
create trigger set_updated_at_generation_jobs
before update on generation_jobs
for each row execute function public.set_updated_at();

drop trigger if exists set_updated_at_claims on claims;
create trigger set_updated_at_claims
before update on claims
for each row execute function public.set_updated_at();

drop trigger if exists set_updated_at_episodes on episodes;
create trigger set_updated_at_episodes
before update on episodes
for each row execute function public.set_updated_at();

drop trigger if exists set_updated_at_tts_segments on tts_segments;
create trigger set_updated_at_tts_segments
before update on tts_segments
for each row execute function public.set_updated_at();

insert into podcast_topics (name, description)
values ('Tech', 'AI, startups, software, gadgets, developer tools, product design, and technology news.')
on conflict (name) do nothing;

do $$
declare
  queue_names text[] := array[
    'research_queue',
    'research_review_queue',
    'script_queue',
    'fact_check_queue',
    'thumbnail_queue',
    'audio_config_queue',
    'audio_generation_queue',
    'publish_queue',
    'dead_letter_queue'
  ];
  q text;
begin
  foreach q in array queue_names loop
    if not exists (select 1 from pgmq.list_queues() where queue_name = q) then
      perform pgmq.create(q);
    end if;
  end loop;
end;
$$;

alter table podcast_topics enable row level security;
alter table generation_jobs enable row level security;
alter table artifacts enable row level security;
alter table agent_runs enable row level security;
alter table sources enable row level security;
alter table claims enable row level security;
alter table episodes enable row level security;
alter table episode_assets enable row level security;
alter table speakers enable row level security;
alter table tts_segments enable row level security;

drop policy if exists "Published episodes are public" on episodes;
create policy "Published episodes are public"
on episodes for select
to anon, authenticated
using (status = 'published');

drop policy if exists "Published episode assets are public" on episode_assets;
create policy "Published episode assets are public"
on episode_assets for select
to anon, authenticated
using (
  exists (
    select 1 from episodes
    where episodes.id = episode_assets.episode_id
      and episodes.status = 'published'
  )
);

drop policy if exists "Public topics are readable" on podcast_topics;
create policy "Public topics are readable"
on podcast_topics for select
to anon, authenticated
using (true);

