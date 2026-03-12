from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from nstaaf.config import get_settings
from nstaaf.corpus import refresh_corpus, status_snapshot
from nstaaf.discovery import discover_episode_listings, write_source_urls
from nstaaf.indexing import build_index, search_index
from nstaaf.site_export import export_site
from nstaaf.snippets import generate_fact_report, generate_snippet_report


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def wait_for_server(host: str, port: int, timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def open_browser_when_ready(host: str, port: int) -> None:
    if wait_for_server(host, port):
        webbrowser.open(f"http://{host}:{port}", new=1)


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

    snippets_parser = subparsers.add_parser(
        "snippets",
        help="Retrieve semantic hits, then curate a few grounded snippets with an LLM.",
    )
    snippets_parser.add_argument("query")
    snippets_parser.add_argument("--top-k", type=int, default=8)
    snippets_parser.add_argument("--max-snippets", type=int, default=3)
    snippets_parser.add_argument("--context-window", type=int, default=1)

    facts_parser = subparsers.add_parser(
        "facts",
        help="Retrieve transcript evidence, then synthesize a few grounded facts with an LLM.",
    )
    facts_parser.add_argument("query")
    facts_parser.add_argument("--top-k", type=int, default=12)
    facts_parser.add_argument("--max-facts", type=int, default=3)
    facts_parser.add_argument("--context-window", type=int, default=2)

    ui_parser = subparsers.add_parser("ui", help="Launch the local Streamlit search UI.")
    ui_parser.add_argument("--port", type=int, default=8501)
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")

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

    if args.command == "snippets":
        print_json(
            generate_snippet_report(
                settings,
                query=args.query,
                top_k=args.top_k,
                max_snippets=args.max_snippets,
                context_window=args.context_window,
            )
        )
        return

    if args.command == "facts":
        print_json(
            generate_fact_report(
                settings,
                query=args.query,
                top_k=args.top_k,
                max_facts=args.max_facts,
                context_window=args.context_window,
            )
        )
        return

    if args.command == "ui":
        app_path = settings.project_root / "streamlit_app.py"
        if not args.no_open:
            threading.Thread(
                target=open_browser_when_ready,
                args=(args.host, args.port),
                daemon=True,
            ).start()
        command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.address",
            args.host,
            "--server.port",
            str(args.port),
            "--server.headless",
            "true",
        ]
        try:
            raise SystemExit(subprocess.run(command, check=False).returncode)
        except KeyboardInterrupt:
            raise SystemExit(130) from None

    if args.command == "export-site":
        print_json(export_site(settings))
        return

    if args.command == "status":
        print_json(status_snapshot(settings))
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
