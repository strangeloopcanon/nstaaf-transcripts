from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nstaaf.config import Settings


@dataclass(frozen=True)
class EpisodeListing:
    slug: str
    title: str
    url: str


def build_session(settings: Settings) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": settings.user_agent})
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def slug_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def get_listing_soup(session: requests.Session, settings: Settings, page_number: int) -> BeautifulSoup:
    response = session.get(
        settings.base_listing_url,
        params={"page": page_number},
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def get_last_page(soup: BeautifulSoup) -> int:
    page_numbers: list[int] = []
    for link in soup.select(".pagination a[href*='?page=']"):
        text = normalize_text(link.get_text(" ", strip=True))
        if text.isdigit():
            page_numbers.append(int(text))
    return max(page_numbers) if page_numbers else 1


def parse_listing_page(soup: BeautifulSoup, settings: Settings) -> list[EpisodeListing]:
    episodes: list[EpisodeListing] = []
    for link in soup.select("article h3 a[href]"):
        href = link.get("href", "").strip()
        if not href:
            continue
        url = urljoin(settings.base_listing_url, href)
        if url.rstrip("/") == settings.base_listing_url.rstrip("/"):
            continue
        slug = slug_from_url(url)
        title = normalize_text(link.get_text(" ", strip=True))
        episodes.append(EpisodeListing(slug=slug, title=title, url=url))
    return episodes


def discover_episode_listings(settings: Settings, max_pages: int | None = None) -> list[EpisodeListing]:
    settings.ensure_directories()
    session = build_session(settings)
    first_page = get_listing_soup(session, settings, page_number=1)
    last_page = get_last_page(first_page)
    if max_pages is not None:
        last_page = min(last_page, max_pages)

    discovered: dict[str, EpisodeListing] = {}
    for page_number in range(1, last_page + 1):
        soup = first_page if page_number == 1 else get_listing_soup(session, settings, page_number)
        for episode in parse_listing_page(soup, settings):
            discovered.setdefault(episode.slug, episode)
    return list(discovered.values())


def write_source_urls(settings: Settings, episodes: Iterable[EpisodeListing]) -> None:
    settings.ensure_directories()
    with settings.source_urls_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["slug", "title", "url"])
        writer.writeheader()
        for episode in episodes:
            writer.writerow(
                {
                    "slug": episode.slug,
                    "title": episode.title,
                    "url": episode.url,
                }
            )


def read_source_urls(settings: Settings) -> list[EpisodeListing]:
    if not settings.source_urls_path.exists():
        return []
    with settings.source_urls_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            EpisodeListing(
                slug=row["slug"].strip(),
                title=row["title"].strip(),
                url=row["url"].strip(),
            )
            for row in reader
            if row.get("slug") and row.get("url")
        ]
