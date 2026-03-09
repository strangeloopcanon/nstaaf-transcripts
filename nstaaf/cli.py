from __future__ import annotations

import argparse
import json

from nstaaf.config import get_settings
from nstaaf.corpus import refresh_corpus, status_snapshot
from nstaaf.discovery import discover_episode_listings, write_source_urls
from nstaaf.indexing import build_index, search_index
from nstaaf.site_export import export_site


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NSTAAF transcript refresh and search.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser("discover", help="Refresh source_urls.csv from Podscripts.")
    discover_parser.add_argument("--max-pages", type=int, default=None)

    refresh_parser = subparsers.add_parser("refresh", help="Download and extract the corpus.")
    refresh_parser.add_argument("--max-pages", type=int, default=None)
    refresh_parser.add_argument("--limit", type=int, default=None)
    refresh_parser.add_argument("--force-download", action="store_true")

    index_parser = subparsers.add_parser("index", help="Build the FAISS embedding index.")
    index_parser.add_argument("--limit", type=int, default=None)

    rebuild_parser = subparsers.add_parser("rebuild", help="Run refresh + index.")
    rebuild_parser.add_argument("--max-pages", type=int, default=None)
    rebuild_parser.add_argument("--limit", type=int, default=None)
    rebuild_parser.add_argument("--force-download", action="store_true")

    search_parser = subparsers.add_parser("search", help="Search the local transcript index.")
    search_parser.add_argument("query")
    search_parser.add_argument("--top-k", type=int, default=5)

    subparsers.add_parser("export-site", help="Generate the MkDocs source tree for the GitHub Pages site.")
    subparsers.add_parser("status", help="Show corpus/index counts.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    settings.ensure_directories()

    if args.command == "discover":
        episodes = discover_episode_listings(settings, max_pages=args.max_pages)
        write_source_urls(settings, episodes)
        print_json({"source_count": len(episodes), "source_urls_path": str(settings.source_urls_path)})
        return

    if args.command == "refresh":
        print_json(
            refresh_corpus(
                settings,
                max_pages=args.max_pages,
                limit=args.limit,
                force_download=args.force_download,
            )
        )
        return

    if args.command == "index":
        print_json(build_index(settings, limit=args.limit))
        return

    if args.command == "rebuild":
        refresh_payload = refresh_corpus(
            settings,
            max_pages=args.max_pages,
            limit=args.limit,
            force_download=args.force_download,
        )
        index_payload = build_index(settings, limit=args.limit)
        print_json({"refresh": refresh_payload, "index": index_payload})
        return

    if args.command == "search":
        print_json(search_index(settings, query=args.query, top_k=args.top_k))
        return

    if args.command == "export-site":
        print_json(export_site(settings))
        return

    if args.command == "status":
        print_json(status_snapshot(settings))
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
