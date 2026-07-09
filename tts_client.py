# ~/nixos-config/modules/nixos/homelab/article2pod-src/tts_client.py
import os
import re
import json
import logging
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

KOKORO_URL = os.environ.get("KOKORO_URL", "http://localhost:8880")
PIPER_URL = os.environ.get("PIPER_URL", "http://mini.lan:10200")
TTS_BACKEND = os.environ.get("TTS_BACKEND", "kokoro")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")

# Kokoro's token limit is ~510 tokens; ~2500 chars is a safe character ceiling
CHUNK_MAX_CHARS = 2500


def _split_chunks(text: str) -> list[str]:
    """Split text into sentence-boundary chunks under CHUNK_MAX_CHARS."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= CHUNK_MAX_CHARS:
            current = (current + " " + sentence).strip() if current else sentence
        else:
            if current:
                chunks.append(current)
            # Sentence itself is longer than limit — hard-split at word boundary
            if len(sentence) > CHUNK_MAX_CHARS:
                words = sentence.split()
                current = ""
                for word in words:
                    if len(current) + len(word) + 1 <= CHUNK_MAX_CHARS:
                        current = (current + " " + word).strip() if current else word
                    else:
                        if current:
                            chunks.append(current)
                        current = word
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks


def _kokoro_synthesize(text: str, voice: str | None = None) -> bytes:
    payload = json.dumps({
        "model": "kokoro",
        "input": text,
        "voice": voice or KOKORO_VOICE,
        "response_format": "mp3",
        "speed": 1.0,
    }).encode()
    req = urllib.request.Request(
        f"{KOKORO_URL}/v1/audio/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def _piper_synthesize(text: str) -> bytes:
    """Call Piper-compatible Wyoming HTTP endpoint (optional, remote)."""
    payload = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        f"{PIPER_URL}/api/tts",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def synthesize(text: str, voice: str | None = None) -> bytes:
    """
    Convert text to MP3 bytes. Splits into chunks, synthesizes each, concatenates.
    Uses TTS_BACKEND env var to select backend (kokoro or piper).
    """
    chunks = _split_chunks(text)
    log.info("Synthesizing %d chunk(s) via %s (voice=%s)", len(chunks), TTS_BACKEND, voice or KOKORO_VOICE)

    audio_parts: list[bytes] = []
    for i, chunk in enumerate(chunks):
        log.info("  chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk))
        if TTS_BACKEND == "kokoro":
            audio_parts.append(_kokoro_synthesize(chunk, voice=voice))
        else:
            audio_parts.append(_piper_synthesize(chunk))

    return b"".join(audio_parts)
