create table if not exists automation_locks (
  name text primary key,
  owner_id text not null,
  expires_at text not null,
  updated_at text not null default ((now() at time zone 'utc')::text)
);
