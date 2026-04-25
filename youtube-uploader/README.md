# Pleopod YouTube Uploader

Standalone uploader for Pleopod video podcasts. It consumes a JSON manifest and
uploads an MP4 to YouTube through the YouTube Data API v3.

The backend can invoke this CLI, but the uploader does not import backend code.

## Auth

YouTube uploads require OAuth 2.0 user consent. Service accounts are not supported
by the YouTube Data API for channel uploads.

Create a Google OAuth client, enable the YouTube Data API, then get a refresh
token:

```bash
cd youtube-uploader
python -m youtube_uploader auth-url \
  --redirect-uri "http://localhost:8080/oauth2/callback"

python -m youtube_uploader exchange-code \
  --code "CODE_FROM_REDIRECT" \
  --redirect-uri "http://localhost:8080/oauth2/callback" \
  --out ./tokens.json
```

Store the refresh token securely as `YOUTUBE_REFRESH_TOKEN`.

## Upload

```bash
export YOUTUBE_CLIENT_ID="..."
export YOUTUBE_CLIENT_SECRET="..."
export YOUTUBE_REFRESH_TOKEN="..."

python -m youtube_uploader upload \
  --manifest ./sample-manifest.json \
  --out ./upload-result.json
```

Use `--dry-run` to validate a manifest without calling YouTube.

## Manifest

```json
{
  "version": 1,
  "videoPath": "/absolute/path/final.mp4",
  "thumbnailPath": "/absolute/path/thumbnail.png",
  "title": "Episode title",
  "description": "Episode description",
  "tags": ["Pleopod", "Podcast", "AI"],
  "categoryId": "28",
  "privacyStatus": "private",
  "selfDeclaredMadeForKids": false,
  "language": "en"
}
```

Notes:

- `privacyStatus` can be `private`, `unlisted`, or `public`.
- Google notes that uploads from unverified API projects can be restricted to
  private visibility.
- Custom thumbnails must be 2MB or smaller and require channel permission.
