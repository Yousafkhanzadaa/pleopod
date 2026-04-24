do $$
begin
  if not exists (select 1 from pgmq.list_queues() where queue_name = 'video_render_queue') then
    perform pgmq.create('video_render_queue');
  end if;
end;
$$;
