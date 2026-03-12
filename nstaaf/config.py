from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_environment() -> None:
    for candidate in (
        PROJECT_ROOT / ".env",
        PROJECT_ROOT.parent / ".env",
        PROJECT_ROOT.parent.parent / ".env",
    ):
        if candidate.exists():
            load_dotenv(candidate, override=False)
            break


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    html_dir: Path
    episodes_dir: Path
    transcripts_dir: Path
    site_docs_dir: Path
    index_dir: Path
    source_urls_path: Path
    index_path: Path
    metadata_path: Path
    manifest_path: Path
    base_listing_url: str
    request_timeout_seconds: int
    user_agent: str
    embedding_model: str
    snippet_model: str
    embedding_batch_size: int
    max_chunk_words: int
    download_workers: int
    download_delay_seconds: float
    openai_api_key: str | None

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.html_dir,
            self.episodes_dir,
            self.transcripts_dir,
            self.site_docs_dir,
            self.index_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    load_environment()
    data_dir = PROJECT_ROOT / "data"
    return Settings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        html_dir=data_dir / "html",
        episodes_dir=data_dir / "episodes",
        transcripts_dir=PROJECT_ROOT / "corpus",
        site_docs_dir=PROJECT_ROOT / "site_docs",
        index_dir=data_dir / "index",
        source_urls_path=data_dir / "source_urls.csv",
        index_path=data_dir / "index" / "faiss.index",
        metadata_path=data_dir / "index" / "metadata.jsonl",
        manifest_path=data_dir / "index" / "manifest.json",
        base_listing_url="https://podscripts.co/podcasts/no-such-thing-as-a-fish",
        request_timeout_seconds=int(os.getenv("NSTAAF_REQUEST_TIMEOUT_SECONDS", "30")),
        user_agent=os.getenv(
            "NSTAAF_USER_AGENT",
            "NSTAAF transcript refresh/1.0 (+local use)",
        ),
        embedding_model=os.getenv("NSTAAF_EMBEDDING_MODEL", "text-embedding-3-small"),
        snippet_model=os.getenv("NSTAAF_SNIPPET_MODEL", "gpt-4.1-mini"),
        embedding_batch_size=int(os.getenv("NSTAAF_EMBEDDING_BATCH_SIZE", "64")),
        max_chunk_words=int(os.getenv("NSTAAF_MAX_CHUNK_WORDS", "180")),
        download_workers=int(os.getenv("NSTAAF_DOWNLOAD_WORKERS", "1")),
        download_delay_seconds=float(os.getenv("NSTAAF_DOWNLOAD_DELAY_SECONDS", "0.5")),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
