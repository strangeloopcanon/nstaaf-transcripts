from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nstaaf.asr import build_asr_document, cleanup_audio_artifacts, format_timestamp, slugify_title
from nstaaf.config import Settings


class AsrTests(unittest.TestCase):
    def test_slugify_title_matches_existing_episode_slug_style(self) -> None:
        self.assertEqual(
            slugify_title("Little Fish: You've Hit The Nail On the Head"),
            "little-fish-youve-hit-the-nail-on-the-head",
        )

    def test_format_timestamp_uses_hour_when_needed(self) -> None:
        self.assertEqual(format_timestamp(420), "07:00")
        self.assertEqual(format_timestamp(3661), "01:01:01")

    def test_build_asr_document_labels_machine_generated_source(self) -> None:
        document = build_asr_document(
            {
                "title": "No Such Thing As Imaginary Flumps",
                "published_at": "2026-04-30T22:35:00+00:00",
                "published_date": "2026-04-30",
                "podcast_url": "https://audioboom.com/posts/8897452",
                "audio_url": "https://audio.example/episode.mp3",
            },
            model="gpt-4o-mini-transcribe",
            segments=[{"timestamp": "00:00", "text": "Hello from the transcript."}],
        )

        self.assertEqual(document["slug"], "no-such-thing-as-imaginary-flumps")
        self.assertEqual(document["source_type"], "machine_generated_asr")
        self.assertEqual(document["episode_date"], "April 30, 2026")
        self.assertIn("gpt-4o-mini-transcribe", document["transcript_source"])
        self.assertEqual(document["word_count"], 5)

    def test_cleanup_audio_artifacts_removes_download_and_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                project_root=root,
                data_dir=root / "data",
                html_dir=root / "data" / "html",
                audio_dir=root / "data" / "audio",
                audio_chunks_dir=root / "data" / "audio_chunks",
                episodes_dir=root / "data" / "episodes",
                transcripts_dir=root / "corpus",
                site_docs_dir=root / "site_docs",
                index_dir=root / "data" / "index",
                source_urls_path=root / "data" / "source_urls.csv",
                freshness_status_path=root / "data" / "freshness_status.json",
                gap_episodes_path=root / "data" / "gap_episodes.json",
                index_path=root / "data" / "index" / "faiss.index",
                metadata_path=root / "data" / "index" / "metadata.jsonl",
                manifest_path=root / "data" / "index" / "manifest.json",
                base_listing_url="https://podscripts.example",
                podcast_feed_url="https://rss.example/feed.xml",
                request_timeout_seconds=30,
                user_agent="test",
                embedding_model="text-embedding-3-small",
                snippet_model="gpt-4.1-mini",
                asr_model="gpt-4o-mini-transcribe",
                asr_chunk_seconds=420,
                asr_audio_bitrate="48k",
                embedding_batch_size=64,
                max_chunk_words=180,
                download_workers=1,
                download_delay_seconds=0.5,
                openai_api_key=None,
            )
            settings.ensure_directories()
            audio_path = settings.audio_dir / "no-such-thing-as-imaginary-flumps.mp3"
            chunk_dir = settings.audio_chunks_dir / "no-such-thing-as-imaginary-flumps"
            chunk_dir.mkdir(parents=True)
            audio_path.write_bytes(b"audio")
            (chunk_dir / "chunk_000.mp3").write_bytes(b"chunk")

            cleanup_audio_artifacts(
                settings,
                {
                    "title": "No Such Thing As Imaginary Flumps",
                    "audio_url": "https://audio.example/no-such-thing-as-imaginary-flumps.mp3",
                },
            )

            self.assertFalse(audio_path.exists())
            self.assertFalse(chunk_dir.exists())


if __name__ == "__main__":
    unittest.main()
