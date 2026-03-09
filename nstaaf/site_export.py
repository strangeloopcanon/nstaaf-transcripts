from __future__ import annotations

import html
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from nstaaf.config import Settings
from nstaaf.corpus import load_episode_documents


RECENT_EPISODE_COUNT = 12


def series_label(document: dict[str, Any]) -> str:
    title = document["title"].lower()
    if "little fish" in title:
        return "Little Fish"
    if "nstaaf" in title or "factball" in title:
        return "NSTAAF special"
    return "Main show"


def sort_key(document: dict[str, Any]) -> tuple[str, str]:
    return (document.get("episode_date_iso") or "0000-00-00", document["title"].lower())


def year_label(document: dict[str, Any]) -> str:
    if document.get("episode_date_iso"):
        return document["episode_date_iso"][:4]
    return "Unknown year"


def episode_link(document: dict[str, Any]) -> str:
    return f"episodes/{document['slug']}.md"


def timestamp_anchor(segment_index: int, timestamp: str) -> str:
    clean = timestamp.replace(":", "-").strip("-")
    if clean:
        return f"t-{clean}"
    return f"segment-{segment_index}"


def render_homepage(documents: list[dict[str, Any]]) -> str:
    recent = sorted(documents, key=sort_key, reverse=True)[:RECENT_EPISODE_COUNT]
    latest = recent[0] if recent else None

    lines = [
        "# NSTAAF Transcript Search",
        "",
        '<div class="nstaaf-hero">',
        '  <p class="nstaaf-kicker">No Such Thing As A Fish transcript archive</p>',
        '  <h2>Search every transcript from one fast static site.</h2>',
        '  <p class="nstaaf-summary">This site uses keyword search powered by Pagefind. Names, phrases, countries, and specific terms work best. It is intentionally not semantic search.</p>',
        '  <div data-pagefind-search class="nstaaf-search"></div>',
        '  <p class="nstaaf-examples"><strong>Try:</strong> <code>mexico avocado</code>, <code>Andrew Hunter Murray</code>, <code>Italy Switzerland</code>, <code>patreon quiz</code></p>',
        "</div>",
        "",
        "## Recent Episodes",
        "",
    ]

    if latest:
        latest_date = latest.get("episode_date") or "Unknown date"
        lines.extend(
            [
                f"The latest transcript in this archive is **{latest['title']}** from **{latest_date}**.",
                "",
            ]
        )

    for document in recent:
        date_text = document.get("episode_date") or "Unknown date"
        lines.append(
            f"- [{document['title']}]({episode_link(document)})"
            f" - {date_text} - {series_label(document)}"
        )

    lines.extend(
        [
            "",
            "## Browse the Archive",
            "",
            f"This site currently includes **{len(documents)}** transcript pages.",
            "",
            "- [Browse all episodes by year](episodes/index.md)",
            "- [About this archive](about.md)",
        ]
    )
    return "\n".join(lines) + "\n"


def render_episode_index(documents: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        grouped[year_label(document)].append(document)

    year_order = sorted(grouped, reverse=True)
    lines = [
        "# Episode Index",
        "",
        "Use the homepage search for the fastest way in. This page is here if you want to browse everything manually.",
        "",
    ]

    for year in year_order:
        entries = sorted(grouped[year], key=sort_key, reverse=True)
        open_attr = " open" if year in {"2026", "2025"} else ""
        lines.append(f"<details{open_attr}>")
        lines.append(f"<summary><strong>{year}</strong> - {len(entries)} episode{'s' if len(entries) != 1 else ''}</summary>")
        lines.append("")
        for document in entries:
            date_text = document.get("episode_date") or "Unknown date"
            lines.append(
                f"- [{document['title']}]({document['slug']}.md)"
                f" - {date_text} - {series_label(document)}"
            )
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def render_about_page(documents: list[dict[str, Any]]) -> str:
    latest = max(documents, key=sort_key) if documents else None
    latest_text = latest.get("episode_date") if latest else "Unknown date"
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "\n".join(
        [
            "# About",
            "",
            "This is a static transcript archive for *No Such Thing As A Fish* and related *Little Fish* episodes.",
            "",
            "- Search is keyword-based, not semantic.",
            "- Transcript text is rendered from the locally extracted corpus without summarization or fact extraction.",
            f"- Current archive size: **{len(documents)}** episodes.",
            f"- Latest episode date in the local corpus: **{latest_text}**.",
            f"- Site export generated: **{build_time}**.",
            "",
            "The public site is designed to stay simple: a search-first homepage, a year-based episode index, and one page per transcript.",
        ]
    ) + "\n"


def render_404_page() -> str:
    return "\n".join(
        [
            "# Page Not Found",
            "",
            "That page does not exist in the static transcript site.",
            "",
            '<div data-pagefind-search class="nstaaf-search"></div>',
            "",
            "- [Go back to the homepage](index.md)",
            "- [Browse the episode archive](episodes/index.md)",
        ]
    ) + "\n"


def render_episode_page(document: dict[str, Any]) -> str:
    date_text = document.get("episode_date") or "Unknown date"
    lines = [
        f"# {document['title']}",
        "",
        '<div class="episode-header">',
        f'  <p><strong>Episode date:</strong> <span data-pagefind-meta="episode_date">{html.escape(date_text)}</span></p>',
        f'  <p><strong>Series:</strong> <span>{html.escape(series_label(document))}</span></p>',
        f'  <p><strong>Source:</strong> <a href="{html.escape(document["url"])}">{html.escape(document["url"])}</a></p>',
        "</div>",
        "",
        '<div class="transcript-content" data-pagefind-body>',
    ]

    for index, segment in enumerate(document["segments"]):
        timestamp = segment.get("timestamp") or ""
        anchor = timestamp_anchor(index, timestamp)
        escaped_text = html.escape(segment["text"])
        if timestamp:
            lines.extend(
                [
                    f'  <p id="{anchor}" class="transcript-line">',
                    f'    <a class="timestamp" href="#{anchor}">{html.escape(timestamp)}</a>',
                    f'    <span class="segment-text">{escaped_text}</span>',
                    "  </p>",
                ]
            )
        else:
            lines.extend(
                [
                    f'  <p id="{anchor}" class="transcript-line">',
                    f'    <span class="segment-text">{escaped_text}</span>',
                    "  </p>",
                ]
            )

    lines.extend(
        [
            "</div>",
            "",
            "## Back to Search",
            "",
            "- [Search the full archive](../index.md)",
            "- [Browse all episodes](index.md)",
        ]
    )
    return "\n".join(lines) + "\n"


def copy_site_assets(settings: Settings) -> None:
    source_dir = settings.project_root / "site_assets"
    target_dir = settings.site_docs_dir / "assets"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir / "assets", target_dir)


def export_site(settings: Settings) -> dict[str, Any]:
    settings.ensure_directories()
    documents = sorted(load_episode_documents(settings), key=sort_key, reverse=True)
    if not documents:
        raise RuntimeError("No extracted episodes found. Run `nstaaf refresh` before exporting the site.")

    if settings.site_docs_dir.exists():
        shutil.rmtree(settings.site_docs_dir)
    settings.site_docs_dir.mkdir(parents=True, exist_ok=True)
    (settings.site_docs_dir / "episodes").mkdir(parents=True, exist_ok=True)

    copy_site_assets(settings)

    (settings.site_docs_dir / "index.md").write_text(render_homepage(documents), encoding="utf-8")
    (settings.site_docs_dir / "about.md").write_text(render_about_page(documents), encoding="utf-8")
    (settings.site_docs_dir / "404.md").write_text(render_404_page(), encoding="utf-8")
    (settings.site_docs_dir / "episodes" / "index.md").write_text(
        render_episode_index(documents),
        encoding="utf-8",
    )

    for document in documents:
        output_path = settings.site_docs_dir / "episodes" / f"{document['slug']}.md"
        output_path.write_text(render_episode_page(document), encoding="utf-8")

    latest = documents[0]
    return {
        "site_docs_dir": str(settings.site_docs_dir),
        "page_count": len(documents) + 4,
        "episode_count": len(documents),
        "latest_episode_title": latest["title"],
        "latest_episode_date": latest.get("episode_date"),
    }
