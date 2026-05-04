from __future__ import annotations

import unittest

from nstaaf.asr import build_asr_document, format_timestamp, slugify_title


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


if __name__ == "__main__":
    unittest.main()
