do $$
begin
  if not exists (select 1 from pgmq.list_queues() where queue_name = 'youtube_upload_queue') then
    perform pgmq.create('youtube_upload_queue');
  end if;
end;
$$;
