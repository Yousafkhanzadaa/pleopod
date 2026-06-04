alter table if exists generation_jobs
  alter column target_duration_seconds set default 90;
