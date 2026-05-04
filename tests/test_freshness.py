from __future__ import annotations

import unittest

from nstaaf.freshness import parse_feed_datetime
from nstaaf.gaps import tapesearch_query
from nstaaf.site_export import render_freshness_notice


class FreshnessTests(unittest.TestCase):
    def test_parse_feed_datetime_returns_utc_iso_and_date(self) -> None:
        published_at, published_date = parse_feed_datetime("Sun, 03 May 2026 22:58:00 +0000")

        self.assertEqual(published_at, "2026-05-03T22:58:00+00:00")
        self.assertEqual(published_date, "2026-05-03")

    def test_render_notice_when_transcript_source_lags_feed(self) -> None:
        notice = "\n".join(
            render_freshness_notice(
                {
                    "generated_at": "2026-05-04T07:58:08+00:00",
                    "latest_podcast_episode": {
                        "title": "Little Fish: You've Hit The Nail On the Head",
                        "published_date": "2026-05-03",
                    },
                    "latest_transcript": {
                        "title": "No Such Thing As A Fish - Little Fish: Not Sponsored By Reba McEntire",
                        "date": "January 18, 2026",
                    },
                    "is_transcript_source_lagging": True,
                    "lag_days": 105,
                    "error": None,
                }
            )
        )

        self.assertIn("Transcript source is behind the podcast feed", notice)
        self.assertIn("May 3, 2026", notice)
        self.assertIn("January 18, 2026", notice)
        self.assertIn("105 days", notice)

    def test_tapesearch_query_targets_show_and_episode_title(self) -> None:
        query = tapesearch_query("No Such Thing As Imaginary Flumps")

        self.assertEqual(
            query,
            '"No Such Thing As A Fish" AND "No Such Thing As Imaginary Flumps"',
        )


if __name__ == "__main__":
    unittest.main()
