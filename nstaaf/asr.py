from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from nstaaf.config import Settings
from nstaaf.corpus import load_episode_documents, write_episode_outputs
from nstaaf.discovery import build_session
from nstaaf.freshness import PodcastFeedEpisode, write_freshness_status
from nstaaf.gaps import build_gap_episodes, write_gap_episodes


ASR_PROMPT = (
    "Transcribe this episode of the podcast No Such Thing As A Fish. "
    "Preserve proper names where possible, including Dan Schreiber, James Harkin, "
    "Anna Ptaszynski, Andrew Hunter Murray, and Little Fish."
)


def slugify_title(value: str) -> str:
    cleaned = value.lower().replace("'", "").replace("’", "")
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return cleaned.strip("-")


def display_title(title: str) -> str:
    if title.startswith("No Such Thing As A Fish - "):
        return title
    return f"No Such Thing As A Fish - {title}"


def format_episode_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def format_timestamp(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def audio_extension(audio_url: str) -> str:
    suffix = Path(urlparse(audio_url).path).suffix.lower()
    if suffix in {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}:
        return suffix
    return ".mp3"


def download_audio(settings: Settings, episode: dict[str, Any], *, force: bool = False) -> Path:
    audio_url = episode.get("audio_url")
    if not audio_url:
        raise RuntimeError(f"RSS episode has no audio enclosure URL: {episode.get('title')}")

    slug = slugify_title(episode["title"])
    output_path = settings.audio_dir / f"{slug}{audio_extension(audio_url)}"
    if output_path.exists() and not force:
        return output_path

    session = build_session(settings)
    with session.get(audio_url, timeout=settings.request_timeout_seconds, stream=True) as response:
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = output_path.with_suffix(output_path.suffix + ".part")
        with partial_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        partial_path.replace(output_path)
    return output_path


def split_audio(settings: Settings, audio_path: Path, slug: str, *, force: bool = False) -> list[Path]:
    chunk_dir = settings.audio_chunks_dir / slug
    if force and chunk_dir.exists():
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    existing_chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
    if existing_chunks and not force:
        return existing_chunks

    for path in existing_chunks:
        path.unlink()

    output_pattern = str(chunk_dir / "chunk_%03d.mp3")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        settings.asr_audio_bitrate,
        "-f",
        "segment",
        "-segment_time",
        str(settings.asr_chunk_seconds),
        "-reset_timestamps",
        "1",
        output_pattern,
    ]
    subprocess.run(command, check=True)
    chunks = sorted(chunk_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise RuntimeError(f"ffmpeg did not create audio chunks for {audio_path}")
    return chunks


def transcribe_audio_chunk(
    client: OpenAI,
    chunk_path: Path,
    *,
    model: str,
    max_attempts: int = 3,
) -> str:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with chunk_path.open("rb") as handle:
                response = client.audio.transcriptions.create(
                    file=handle,
                    model=model,
                    prompt=ASR_PROMPT,
                    response_format="text",
                    timeout=600,
                )
            if isinstance(response, str):
                return response.strip()
            return getattr(response, "text", str(response)).strip()
        except Exception as exc:  # pragma: no cover - exercised only on live API failures
            last_error = exc
            if attempt == max_attempts:
                break
            time.sleep(2**attempt)
    raise RuntimeError(f"Could not transcribe {chunk_path}: {last_error}") from last_error


def build_asr_document(
    episode: dict[str, Any] | PodcastFeedEpisode,
    *,
    model: str,
    segments: list[dict[str, str]],
) -> dict[str, Any]:
    if isinstance(episode, PodcastFeedEpisode):
        episode_data = {
            "title": episode.title,
            "published_at": episode.published_at,
            "published_date": episode.published_date,
            "podcast_url": episode.url,
            "audio_url": episode.audio_url,
        }
    else:
        episode_data = episode

    transcript_text = "\n\n".join(
        f"[{segment['timestamp']}] {segment['text']}".strip() if segment.get("timestamp") else segment["text"]
        for segment in segments
        if segment.get("text")
    )
    title = display_title(episode_data["title"])
    slug = slugify_title(episode_data["title"])
    return {
        "slug": slug,
        "title": title,
        "url": episode_data.get("podcast_url"),
        "audio_url": episode_data.get("audio_url"),
        "source_type": "machine_generated_asr",
        "transcript_source": f"OpenAI {model} transcription from official RSS audio",
        "quality_note": "Machine-generated transcript; may contain transcription errors.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "episode_date": format_episode_date(episode_data.get("published_date")),
        "episode_date_iso": episode_data.get("published_date"),
        "published_at": episode_data.get("published_at"),
        "asr_model": model,
        "segment_count": len(segments),
        "word_count": len(transcript_text.split()),
        "segments": segments,
        "transcript_text": transcript_text,
    }


def transcribe_episode(
    settings: Settings,
    episode: dict[str, Any],
    *,
    client: OpenAI,
    model: str,
    force: bool = False,
) -> dict[str, Any]:
    slug = slugify_title(episode["title"])
    audio_path = download_audio(settings, episode, force=force)
    chunk_paths = split_audio(settings, audio_path, slug, force=force)
    segments = []
    for index, chunk_path in enumerate(chunk_paths):
        text = transcribe_audio_chunk(client, chunk_path, model=model)
        if text:
            segments.append(
                {
                    "timestamp": format_timestamp(index * settings.asr_chunk_seconds),
                    "text": text,
                }
            )
    if not segments:
        raise RuntimeError(f"Transcription produced no text for {episode['title']}")
    return build_asr_document(episode, model=model, segments=segments)


def backfill_asr_transcripts(
    settings: Settings,
    *,
    limit: int | None = None,
    model: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not settings.openai_api_key and not dry_run:
        raise RuntimeError("OPENAI_API_KEY is required to run ASR backfill.")

    settings.ensure_directories()
    documents = load_episode_documents(settings)
    gap_payload = build_gap_episodes(settings, documents)
    if gap_payload.get("error"):
        raise RuntimeError(f"Could not build RSS gap list: {gap_payload['error']}")

    episodes = list(reversed(gap_payload.get("episodes") or []))
    if limit is not None:
        episodes = episodes[:limit]

    selected_model = model or settings.asr_model
    payload: dict[str, Any] = {
        "model": selected_model,
        "dry_run": dry_run,
        "gap_episode_count": len(gap_payload.get("episodes") or []),
        "selected_count": len(episodes),
        "written_count": 0,
        "skipped_count": 0,
        "episodes": [],
    }

    if dry_run:
        payload["episodes"] = [
            {
                "title": episode["title"],
                "published_date": episode.get("published_date"),
                "podcast_url": episode.get("podcast_url"),
                "audio_url": episode.get("audio_url"),
                "slug": slugify_title(episode["title"]),
            }
            for episode in episodes
        ]
        return payload

    client = OpenAI(api_key=settings.openai_api_key)
    for episode in episodes:
        slug = slugify_title(episode["title"])
        episode_path = settings.episodes_dir / f"{slug}.json"
        transcript_path = settings.transcripts_dir / f"{slug}.md"
        if episode_path.exists() and transcript_path.exists() and not force:
            payload["skipped_count"] += 1
            payload["episodes"].append({"title": episode["title"], "slug": slug, "status": "skipped"})
            continue

        document = transcribe_episode(settings, episode, client=client, model=selected_model, force=force)
        write_episode_outputs(settings, document)
        payload["written_count"] += 1
        payload["episodes"].append(
            {
                "title": episode["title"],
                "slug": slug,
                "status": "written",
                "word_count": document["word_count"],
                "segment_count": document["segment_count"],
            }
        )

    updated_documents = load_episode_documents(settings)
    payload["freshness"] = write_freshness_status(settings, updated_documents)
    payload["gap_episodes"] = write_gap_episodes(settings, updated_documents)
    return payload
