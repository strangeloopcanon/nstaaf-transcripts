from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
import requests

from nstaaf.config import Settings
from nstaaf.discovery import EpisodeListing, build_session, discover_episode_listings, read_source_urls, write_source_urls

THREAD_LOCAL = threading.local()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_episode_date(raw_value: str | None) -> tuple[str | None, str | None]:
    if not raw_value:
        return None, None
    cleaned = normalize_text(raw_value.replace("Episode Date:", ""))
    try:
        iso_value = datetime.strptime(cleaned, "%B %d, %Y").date().isoformat()
    except ValueError:
        iso_value = None
    return cleaned, iso_value


def parse_episode_html(html: str, slug: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = normalize_text(
        (soup.select_one("h1.page-heading") or soup.find("title")).get_text(" ", strip=True)
    )
    raw_date = None
    if date_node := soup.select_one(".episode_date"):
        raw_date = date_node.get_text(" ", strip=True)
    episode_date, episode_date_iso = parse_episode_date(raw_date)

    segments: list[dict[str, str]] = []
    for block in soup.select(".podcast-transcript .single-sentence"):
        timestamp_text = ""
        if timestamp_node := block.select_one(".pod_timestamp_indicator"):
            timestamp_text = normalize_text(timestamp_node.get_text(" ", strip=True))
            timestamp_text = timestamp_text.replace("Starting point is ", "")

        sentence_bits = [
            normalize_text(node.get_text(" ", strip=True))
            for node in block.select(".pod_text.transcript-text")
        ]
        sentence_bits = [bit for bit in sentence_bits if bit]
        if not sentence_bits:
            continue
        segments.append({"timestamp": timestamp_text, "text": " ".join(sentence_bits)})

    if not segments:
        transcript_bits = [
            normalize_text(node.get_text(" ", strip=True))
            for node in soup.select(".pod_text.transcript-text")
        ]
        transcript_bits = [bit for bit in transcript_bits if bit]
        if transcript_bits:
            segments.append({"timestamp": "", "text": " ".join(transcript_bits)})

    transcript_text = "\n\n".join(
        f"[{segment['timestamp']}] {segment['text']}".strip() if segment["timestamp"] else segment["text"]
        for segment in segments
    )

    return {
        "slug": slug,
        "title": title,
        "url": url,
        "episode_date": episode_date,
        "episode_date_iso": episode_date_iso,
        "segment_count": len(segments),
        "word_count": len(transcript_text.split()),
        "segments": segments,
        "transcript_text": transcript_text,
    }


def render_transcript_markdown(document: dict[str, Any]) -> str:
    lines = [f"# {document['title']}", ""]
    if document.get("episode_date"):
        lines.append(f"- Episode date: {document['episode_date']}")
    lines.append(f"- Source: {document['url']}")
    lines.append(f"- Slug: {document['slug']}")
    lines.extend(["", "## Transcript", ""])
    for segment in document["segments"]:
        text = segment["text"]
        timestamp = segment.get("timestamp") or ""
        if timestamp:
            lines.append(f"[{timestamp}] {text}")
        else:
            lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def download_episode_html(
    settings: Settings,
    listing: EpisodeListing,
    *,
    session: requests.Session,
    force_download: bool = False,
) -> str:
    settings.ensure_directories()
    output_path = settings.html_dir / f"{listing.slug}.html"
    if output_path.exists() and not force_download:
        return output_path.read_text(encoding="utf-8")

    response = session.get(listing.url, timeout=settings.request_timeout_seconds)
    response.raise_for_status()
    output_path.write_text(response.text, encoding="utf-8")
    if settings.download_delay_seconds > 0:
        time.sleep(settings.download_delay_seconds)
    return response.text


def get_thread_session(settings: Settings) -> requests.Session:
    session = getattr(THREAD_LOCAL, "session", None)
    if session is None:
        session = build_session(settings)
        THREAD_LOCAL.session = session
    return session


def write_episode_outputs(settings: Settings, document: dict[str, Any]) -> None:
    episode_path = settings.episodes_dir / f"{document['slug']}.json"
    transcript_path = settings.transcripts_dir / f"{document['slug']}.md"
    episode_path.write_text(json.dumps(document, ensure_ascii=True, indent=2), encoding="utf-8")
    transcript_path.write_text(render_transcript_markdown(document), encoding="utf-8")


def refresh_corpus(
    settings: Settings,
    *,
    max_pages: int | None = None,
    limit: int | None = None,
    force_download: bool = False,
) -> dict[str, Any]:
    settings.ensure_directories()
    episodes = discover_episode_listings(settings, max_pages=max_pages)
    write_source_urls(settings, episodes)

    if limit is not None:
        episodes = episodes[:limit]

    def refresh_one(listing: EpisodeListing) -> tuple[bool, str]:
        html_path = settings.html_dir / f"{listing.slug}.html"
        episode_path = settings.episodes_dir / f"{listing.slug}.json"
        transcript_path = settings.transcripts_dir / f"{listing.slug}.md"
        existed = html_path.exists()
        if existed and episode_path.exists() and transcript_path.exists() and not force_download:
            return True, listing.slug
        html = download_episode_html(
            settings,
            listing,
            session=get_thread_session(settings),
            force_download=force_download,
        )
        document = parse_episode_html(html, listing.slug, listing.url)
        write_episode_outputs(settings, document)
        return existed, listing.slug

    downloaded = 0
    extracted = 0
    with ThreadPoolExecutor(max_workers=max(1, settings.download_workers)) as executor:
        futures = [executor.submit(refresh_one, listing) for listing in episodes]
        for future in as_completed(futures):
            existed, _slug = future.result()
            if not existed or force_download:
                downloaded += 1
            extracted += 1

    return {
        "source_count": len(read_source_urls(settings)),
        "processed_count": extracted,
        "downloaded_count": downloaded,
        "episodes_dir": str(settings.episodes_dir),
        "transcripts_dir": str(settings.transcripts_dir),
    }


def load_episode_documents(settings: Settings, limit: int | None = None) -> list[dict[str, Any]]:
    paths = sorted(settings.episodes_dir.glob("*.json"))
    if limit is not None:
        paths = paths[:limit]
    documents: list[dict[str, Any]] = []
    for path in paths:
        documents.append(json.loads(path.read_text(encoding="utf-8")))
    return documents


def status_snapshot(settings: Settings) -> dict[str, Any]:
    settings.ensure_directories()
    source_urls = read_source_urls(settings)
    episode_docs = load_episode_documents(settings)
    latest_episode = None
    dated_episodes = [doc for doc in episode_docs if doc.get("episode_date_iso")]
    if dated_episodes:
        latest_episode = max(dated_episodes, key=lambda doc: doc["episode_date_iso"])

    return {
        "source_url_count": len(source_urls),
        "html_count": len(list(settings.html_dir.glob("*.html"))),
        "episode_json_count": len(episode_docs),
        "transcript_markdown_count": len(list(settings.transcripts_dir.glob("*.md"))),
        "index_exists": settings.index_path.exists(),
        "metadata_exists": settings.metadata_path.exists(),
        "latest_episode_title": latest_episode["title"] if latest_episode else None,
        "latest_episode_date": latest_episode["episode_date"] if latest_episode else None,
    }
