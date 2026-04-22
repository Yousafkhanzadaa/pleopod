do $$
declare
  job_record record;
begin
  for job_record in
    select id
    from generation_jobs
    where status = 'awaiting_research_approval'
       or current_step = 'research_review'
  loop
    update generation_jobs
    set status = 'queued',
        current_step = 'script',
        error = coalesce(nullif(error, ''), 'Research review stage removed; resumed at script.'),
        updated_at = now()
    where id = job_record.id;

    perform pgmq.send(
      'script_queue',
      jsonb_build_object(
        'job_id', job_record.id::text,
        'step', 'script',
        'attempt', 1
      ),
      0
    );
  end loop;
end;
$$;

alter table generation_jobs
  drop constraint if exists generation_jobs_status_check;

alter table generation_jobs
  add constraint generation_jobs_status_check check (
    status in (
      'queued', 'running', 'awaiting_script_approval',
      'completed', 'failed', 'canceled'
    )
  );
