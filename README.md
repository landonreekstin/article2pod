# article2pod

Converts article URLs to MP3 podcast episodes, served as a private per-user RSS feed.
Self-hosted, TTS-powered, VPN-friendly.

## How it works

```
Client (VPN) → nginx → article2pod-api (FastAPI, port 8100)
  ├── POST /add              queue an article URL
  ├── GET  /rss/{token}      per-user podcast RSS feed
  ├── GET  /                 web dashboard (queue, voice selector, admin)
  └── GET  /audio/*.mp3      MP3 files (served via nginx static)

article2pod-worker (oneshot, run every 2 min):
  DB queued → trafilatura extract → [FlareSolverr fallback for Cloudflare]
            → Kokoro-FastAPI TTS (CPU, port 8880) or Piper (optional remote)
            → ffmpeg concat + ID3 tags
            → {audio_dir}/{guid}.mp3
            → DB done
```

## Features

- Web dashboard with queue view, delete, voice selector, and reprocess
- Per-user isolation: each user gets their own token and RSS feed
- Admin dashboard for creating/deleting users and viewing all articles
- Per-article voice override: reprocess any article with a different voice
- Kokoro TTS backend (local, CPU); optional Piper backend (remote)
- FlareSolverr fallback for Cloudflare-protected articles
- Multi-chunk synthesis for long articles (Kokoro token limit workaround)

## Running locally

Requires [Nix](https://nixos.org/) with flakes enabled.

```bash
git clone https://github.com/landonreekstin/article2pod
cd article2pod
nix develop

export ARTICLE2POD_TOKEN=mytoken
export ARTICLE2POD_DB=/tmp/article2pod.sqlite
export ARTICLE2POD_AUDIO=/tmp/article2pod-audio
mkdir -p $ARTICLE2POD_AUDIO

# Terminal 1 — API server
uvicorn app:app --reload --port 8100

# Terminal 2 — run the worker once
python worker.py
```

Open http://localhost:8100 and use `mytoken` to authenticate.
You will also need a running [Kokoro-FastAPI](https://github.com/remsky/kokoro-fastapi)
instance (or set `TTS_BACKEND=piper` with a reachable Piper endpoint).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ARTICLE2POD_TOKEN` | (required) | Admin bearer token |
| `ARTICLE2POD_DB` | `/var/lib/article2pod/db.sqlite` | SQLite path |
| `ARTICLE2POD_AUDIO` | `/mnt/storage/podcasts/audio` | MP3 output directory |
| `ARTICLE2POD_HOSTNAME` | `reader.lan` | Hostname used in RSS feed URLs |
| `ARTICLE2POD_TITLE` | `Article Podcast` | RSS feed title |
| `ARTICLE2POD_AUTHOR` | `lando` | Default author name |
| `ARTICLE2POD_DESCRIPTION` | `Articles converted to audio` | RSS feed description |
| `KOKORO_URL` | `http://localhost:8880` | Kokoro-FastAPI endpoint |
| `KOKORO_VOICE` | `af_heart` | Default voice |
| `TTS_BACKEND` | `kokoro` | `kokoro` or `piper` |
| `PIPER_URL` | `http://mini.lan:10200` | Piper Wyoming HTTP endpoint |
| `FLARESOLVERR_URL` | `http://localhost:8191` | FlareSolverr endpoint |

## NixOS deployment

This repo is packaged as a Nix flake. The
[nixos-config](https://github.com/landonreekstin/nixos-config) repo consumes it as a flake
input and handles systemd services, Docker (Kokoro), nginx, sops secrets, and firewall rules.

## Adding articles

### Android — HTTP Shortcuts app

1. Install **HTTP Shortcuts** (F-Droid or Play Store)
2. Create a new shortcut:
   - **Method**: POST
   - **URL**: `http://reader.lan/add`
   - **Headers**: `Authorization: Bearer <your-token>`, `Content-Type: application/json`
   - **Body**: `{"url": "{shared_text}"}`
   - **Share target**: enable "URL" sharing
3. Phone must be connected to the VPN to submit

### Desktop — bookmarklet

Paste this into your browser's bookmarks bar (replace `TOKEN` and hostname):

```javascript
javascript:(function(){
  var u=encodeURIComponent(location.href);
  fetch('http://reader.lan/add',{
    method:'POST',
    headers:{'Authorization':'Bearer TOKEN','Content-Type':'application/json'},
    body:JSON.stringify({url:location.href})
  }).then(r=>r.json()).then(d=>alert('article2pod: '+d.status));
})();
```

## Subscribing in AntennaPod

1. Open AntennaPod → Add Podcast → Add podcast by RSS address
2. Enter: `http://reader.lan/rss/<your-token>`
3. Phone must be on the VPN to subscribe and to stream/download episodes

## Switching TTS backend

Set `TTS_BACKEND=piper` and `PIPER_URL=http://<host>:10200` in your environment.
Kokoro is the default and primary backend; Piper is an optional remote alternative.

## Blocking a bad Cloudflare page

If FlareSolverr can't bypass a page, the article will be marked `failed` in the DB.
Check logs: `journalctl -u article2pod-worker --since "1 hour ago"`

You can retry a failed article by resetting it in the DB:
```bash
sudo -u article2pod sqlite3 /var/lib/article2pod/db.sqlite \
  "UPDATE articles SET status='queued', error=NULL WHERE url='https://...';"
```

## Monitoring (NixOS)

```bash
journalctl -u article2pod-api -f
journalctl -u article2pod-worker -f
journalctl -u docker-kokoro-fastapi -f
systemctl status article2pod-worker.timer
```

## License

GPL-3.0 — see [LICENSE](LICENSE)
