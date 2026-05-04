from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from nstaaf.config import Settings
from nstaaf.discovery import build_session


@dataclass(frozen=True)
class PodcastFeedEpisode:
    title: str
    published_at: str | None
    published_date: str | None
    url: str | None


def parse_feed_datetime(raw_value: str | None) -> tuple[str | None, str | None]:
    if not raw_value:
        return None, None
    try:
        value = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError):
        return raw_value, None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.isoformat(), value.date().isoformat()


def fetch_latest_podcast_episode(settings: Settings) -> PodcastFeedEpisode:
    session = build_session(settings)
    response = session.get(settings.podcast_feed_url, timeout=settings.request_timeout_seconds)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    channel = root.find("channel")
    item = channel.find("item") if channel is not None else None
    if item is None:
        raise RuntimeError("Podcast RSS feed did not contain any episodes.")

    published_at, published_date = parse_feed_datetime(item.findtext("pubDate"))
    return PodcastFeedEpisode(
        title=(item.findtext("title") or "").strip(),
        published_at=published_at,
        published_date=published_date,
        url=(item.findtext("link") or "").strip() or None,
    )


def latest_transcript_document(documents: list[dict]) -> dict | None:
    dated = [document for document in documents if document.get("episode_date_iso")]
    if not dated:
        return None
    return max(dated, key=lambda document: document["episode_date_iso"])


def build_freshness_status(settings: Settings, documents: list[dict]) -> dict:
    latest_transcript = latest_transcript_document(documents)
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": generated_at,
        "transcript_source_url": settings.base_listing_url,
        "podcast_feed_url": settings.podcast_feed_url,
        "latest_transcript": None,
        "latest_podcast_episode": None,
        "is_transcript_source_lagging": None,
        "lag_days": None,
        "error": None,
    }

    if latest_transcript:
        payload["latest_transcript"] = {
            "title": latest_transcript.get("title"),
            "date": latest_transcript.get("episode_date"),
            "date_iso": latest_transcript.get("episode_date_iso"),
            "url": latest_transcript.get("url"),
            "slug": latest_transcript.get("slug"),
        }

    try:
        latest_podcast = fetch_latest_podcast_episode(settings)
    except Exception as exc:
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return payload

    payload["latest_podcast_episode"] = asdict(latest_podcast)
    transcript_date = latest_transcript.get("episode_date_iso") if latest_transcript else None
    podcast_date = latest_podcast.published_date
    if transcript_date and podcast_date:
        transcript_dt = datetime.fromisoformat(transcript_date).date()
        podcast_dt = datetime.fromisoformat(podcast_date).date()
        lag_days = (podcast_dt - transcript_dt).days
        payload["is_transcript_source_lagging"] = lag_days > 0
        payload["lag_days"] = max(0, lag_days)

    return payload


def write_freshness_status(settings: Settings, documents: list[dict]) -> dict:
    payload = build_freshness_status(settings, documents)
    settings.freshness_status_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def read_freshness_status(settings: Settings) -> dict | None:
    if not settings.freshness_status_path.exists():
        return None
    return json.loads(settings.freshness_status_path.read_text(encoding="utf-8"))
