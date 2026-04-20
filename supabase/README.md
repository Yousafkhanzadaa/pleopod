# Supabase Setup

Apply migrations with the Supabase CLI:

```bash
supabase db push
```

The initial migration enables `pgmq`, creates durable pipeline queues, adds the podcast metadata tables, enables RLS, and exposes only published episodes/assets to public API roles.

Backend services should connect with a trusted Postgres connection string or service credentials. Do not expose the service role key or direct database credentials to the mobile app.

