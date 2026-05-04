from __future__ import annotations

import json
from datetime import datetime, timezone

from nstaaf.config import Settings
from nstaaf.freshness import fetch_podcast_episodes, latest_transcript_document


def build_gap_episodes(settings: Settings, documents: list[dict]) -> dict:
    latest_transcript = latest_transcript_document(documents)
    latest_transcript_date = latest_transcript.get("episode_date_iso") if latest_transcript else None
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_local_transcript": None,
        "podcast_feed_url": settings.podcast_feed_url,
        "episodes": [],
        "error": None,
    }

    if latest_transcript:
        payload["latest_local_transcript"] = {
            "title": latest_transcript.get("title"),
            "date": latest_transcript.get("episode_date"),
            "date_iso": latest_transcript.get("episode_date_iso"),
            "url": latest_transcript.get("url"),
            "slug": latest_transcript.get("slug"),
        }

    if not latest_transcript_date:
        return payload

    try:
        podcast_episodes = fetch_podcast_episodes(settings)
    except Exception as exc:
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return payload

    gap = []
    for episode in podcast_episodes:
        if not episode.published_date or episode.published_date <= latest_transcript_date:
            continue
        gap.append(
            {
                "title": episode.title,
                "published_at": episode.published_at,
                "published_date": episode.published_date,
                "podcast_url": episode.url,
                "audio_url": episode.audio_url,
            }
        )
    payload["episodes"] = gap
    return payload


def write_gap_episodes(settings: Settings, documents: list[dict]) -> dict:
    payload = build_gap_episodes(settings, documents)
    settings.gap_episodes_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def read_gap_episodes(settings: Settings) -> dict | None:
    if not settings.gap_episodes_path.exists():
        return None
    return json.loads(settings.gap_episodes_path.read_text(encoding="utf-8"))
