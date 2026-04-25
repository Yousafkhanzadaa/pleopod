# YouTube Upload System

Reviewed: April 25, 2026.

Pleopod can publish generated video podcasts to YouTube as a separate execution
plane after Remotion rendering.

## Why Separate

The backend should not own YouTube API details. It should only:

- build a YouTube upload manifest
- provide the rendered MP4 and thumbnail as local files
- invoke the standalone uploader
- store the returned YouTube video id and URL

The standalone uploader lives in:

```text
youtube-uploader/
```

It imports no backend code and can be run by hand, in CI, or by a dedicated
uploader worker.

## Flow

```text
VideoRenderAgent
  -> stores episodes/{episode_id}/video/final.mp4
  -> queues youtube_upload when ENABLE_YOUTUBE_UPLOADING=true

YouTubeUploadAgent
  -> reads episode metadata, thumbnail, and final MP4
  -> writes jobs/{job_id}/youtube/upload_manifest.json
  -> invokes youtube-uploader CLI
  -> writes episodes/{episode_id}/youtube/upload_result.json
  -> creates episode asset asset_type='youtube_video'
  -> marks job completed
```

## Setup

Enable the YouTube Data API in Google Cloud, create an OAuth client, and grant
consent for:

```text
https://www.googleapis.com/auth/youtube.upload
```

Generate a refresh token with:

```bash
cd youtube-uploader
python -m youtube_uploader auth-url \
  --redirect-uri "http://localhost:8080/oauth2/callback"

python -m youtube_uploader exchange-code \
  --code "CODE_FROM_REDIRECT" \
  --redirect-uri "http://localhost:8080/oauth2/callback" \
  --out ./tokens.json
```

Configure the worker:

```env
ENABLE_YOUTUBE_UPLOADING=true
YOUTUBE_UPLOADER_PATH=youtube-uploader
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...
YOUTUBE_DEFAULT_PRIVACY_STATUS=private
YOUTUBE_DEFAULT_CATEGORY_ID=28
```

Set `YOUTUBE_DEFAULT_PRIVACY_STATUS=private` for first launches. Google may force
private uploads for projects that have not completed API compliance verification.

## Manifest

The backend builds a manifest with:

- local `videoPath`
- local `thumbnailPath`
- title
- description
- tags
- category id
- privacy status
- made-for-kids declaration
- notification setting

The persisted manifest artifact strips local paths and records artifact ids
instead, so stored artifacts remain meaningful after the temp directory is gone.
