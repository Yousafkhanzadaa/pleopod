# API

## Admin

All admin endpoints require:

```http
x-admin-api-key: <ADMIN_API_KEY>
```

or a Supabase user access token whose `app_metadata.role` is `admin`. Supabase JWTs
are verified through the project JWKS endpoint:

```text
https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json
```

### Create Generation Job

```http
POST /admin/generation-jobs
```

Body:

```json
{
  "topic": "The latest state of AI coding agents",
  "category": "Tech",
  "audience": "curious tech listeners",
  "target_duration_seconds": 600,
  "language": "en",
  "tone": "clear, smart, conversational",
  "source_urls": [],
  "auto_publish": false
}
```

### Get Job Detail

```http
GET /admin/generation-jobs/{job_id}
```

Includes agent runs and artifacts.

### Approval Gates

```http
POST /admin/generation-jobs/{job_id}/approve-script
POST /admin/generation-jobs/{job_id}/publish
```

## Public

```http
GET /episodes
GET /episodes/{slug}
GET /episodes/{episode_id}/stream-url
```
