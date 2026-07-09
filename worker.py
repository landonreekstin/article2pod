# ~/nixos-config/modules/nixos/homelab/article2pod-src/worker.py
"""
Oneshot worker: pick one queued article, extract, synthesize, write MP3, update DB.
Run as a systemd oneshot service on a timer.
"""
import os
import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import db
import extractor
import tts_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("worker")

AUDIO_DIR = os.environ.get("ARTICLE2POD_AUDIO", "/mnt/storage/podcasts/audio")


def _write_mp3(audio_bytes: bytes, guid: str, title: str,
               author: str, pub_date: str, podcast_title: str) -> tuple[Path, int, int]:
    """Write audio bytes to final MP3 with ID3 tags via ffmpeg. Returns (path, duration_secs, size_bytes)."""
    audio_dir = Path(AUDIO_DIR)
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_path = audio_dir / f"{guid}.mp3"

    # Write raw audio to temp file, use ffmpeg to add ID3 tags cleanly
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        cmd = [
            "ffmpeg", "-y", "-i", tmp_path,
            "-c:a", "copy",
            "-id3v2_version", "3",
            "-metadata", f"title={title}",
            "-metadata", f"artist={author}",
            "-metadata", f"album={podcast_title}",
            "-metadata", f"date={pub_date}",
            "-metadata", "genre=Podcast",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        os.unlink(tmp_path)

    size_bytes = out_path.stat().st_size

    # Get duration via ffprobe
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out_path)],
        capture_output=True, text=True,
    )
    try:
        duration = int(float(probe.stdout.strip()))
    except (ValueError, TypeError):
        duration = 0

    return out_path, duration, size_bytes


def run():
    admin_token = os.environ.get("ARTICLE2POD_TOKEN", "")
    default_voice = os.environ.get("KOKORO_VOICE", "af_heart")
    db.init_db(admin_token=admin_token, default_voice=default_voice)
    row = db.get_next_queued()
    if row is None:
        log.info("No queued articles — nothing to do")
        return

    article_id = row["id"]
    url = row["url"]
    guid = row["guid"]
    log.info("Processing article %d: %s", article_id, url)

    db.mark_processing(article_id)

    podcast_title = os.environ.get("ARTICLE2POD_TITLE", "Article Podcast")
    podcast_author = os.environ.get("ARTICLE2POD_AUTHOR", "lando")

    try:
        # Stage 1: Extract
        article = extractor.extract(url)
        title = article["title"]
        author = article["author"] or podcast_author
        pub_date = article["pub_date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        text = article["text"]
        log.info("Extracted: '%s' by %s (%d chars)", title, author, len(text))

        # Stage 2: TTS — per-article voice overrides user default
        voice = row["voice"] or db.get_user_voice(row["user_id"], fallback=os.environ.get("KOKORO_VOICE", "af_heart"))
        audio_bytes = tts_client.synthesize(text, voice=voice)
        log.info("Synthesized %d bytes of audio", len(audio_bytes))

        # Stage 3: Write MP3
        out_path, duration, size_bytes = _write_mp3(
            audio_bytes, guid, title, author, pub_date, podcast_title
        )
        log.info("Wrote %s (%d bytes, %ds)", out_path, size_bytes, duration)

        # Stage 4: Update DB
        db.mark_done(article_id, title, author, pub_date, duration, size_bytes)
        log.info("Done: article %d → %s", article_id, guid)

    except Exception as e:
        log.error("Failed processing article %d: %s", article_id, e, exc_info=True)
        db.mark_failed(article_id, str(e))


if __name__ == "__main__":
    run()
