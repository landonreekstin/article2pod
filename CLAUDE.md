# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What this is

article2pod is a self-hosted read-it-later service that converts article URLs to MP3 podcast
episodes, served as a private per-user RSS feed. It is designed for homelab deployment behind
a VPN.

## Source layout

```
app.py          FastAPI web server — REST API, dashboard UI, RSS feed
db.py           SQLite database layer (users, articles, settings)
extractor.py    Article fetching and text extraction via trafilatura
tts_client.py   TTS synthesis client — Kokoro (primary) or Piper (optional)
worker.py       Oneshot worker — dequeues one article, synthesizes, writes MP3
flake.nix       Nix package (article2pod-api and article2pod-worker binaries)
```

## Key env vars

| Variable | Default | Purpose |
|---|---|---|
| `ARTICLE2POD_TOKEN` | (required) | Admin bearer token (doubles as lando's user token) |
| `ARTICLE2POD_DB` | `/var/lib/article2pod/db.sqlite` | SQLite path |
| `ARTICLE2POD_AUDIO` | `/mnt/storage/podcasts/audio` | MP3 output directory |
| `ARTICLE2POD_HOSTNAME` | `reader.lan` | Hostname used in RSS feed URLs |
| `ARTICLE2POD_TITLE` | `Article Podcast` | RSS feed title |
| `ARTICLE2POD_AUTHOR` | `lando` | Default author |
| `ARTICLE2POD_DESCRIPTION` | `Articles converted to audio` | RSS feed description |
| `KOKORO_URL` | `http://localhost:8880` | Kokoro-FastAPI TTS endpoint |
| `KOKORO_VOICE` | `af_heart` | Default Kokoro voice |
| `TTS_BACKEND` | `kokoro` | `kokoro` or `piper` |
| `PIPER_URL` | `http://mini.lan:10200` | Piper Wyoming HTTP endpoint |
| `FLARESOLVERR_URL` | `http://localhost:8191` | FlareSolverr bypass endpoint |

## Running locally (dev shell)

```bash
nix develop
export ARTICLE2POD_TOKEN=mytoken
export ARTICLE2POD_DB=/tmp/article2pod.sqlite
export ARTICLE2POD_AUDIO=/tmp/article2pod-audio
mkdir -p $ARTICLE2POD_AUDIO

# Start the API
uvicorn app:app --reload --port 8100

# Run the worker once
python worker.py
```

The API will be at http://localhost:8100. Open the dashboard at http://localhost:8100/
using `Authorization: Bearer mytoken` (or the token prompt on the dashboard).

## Architecture notes

- `worker.py` is a oneshot script — it processes exactly one queued article per invocation.
  It is intended to be run on a timer (e.g. every 2 minutes via systemd).
- Per-article voice override: `articles.voice` takes priority over `users.voice`.
- Multi-user: each user has a token and gets their own RSS feed at `/rss/{token}`.
  Admin dashboard lives at the root `/` using the admin token.
- The `feedgen` dependency generates the RSS/Atom feed served at `/rss/{token}`.
- `trafilatura` extracts article text; FlareSolverr is the fallback for Cloudflare-protected pages.

## NixOS packaging

This repo is consumed by [landonreekstin/nixos-config](https://github.com/landonreekstin/nixos-config)
as a flake input. The NixOS module there handles systemd services, Docker (Kokoro), nginx,
sops secrets, and firewall rules. This repo only provides the Python application and its
Nix package — no NixOS deployment logic lives here.

## Making changes

1. Edit Python source files
2. Test locally with `nix develop` (see above)
3. Commit to main
4. In nixos-config: run `nix flake update article2pod` then `rebuild` on optiplex-nas to deploy
