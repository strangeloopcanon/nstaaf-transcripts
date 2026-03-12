from __future__ import annotations

import json
import re
from typing import Any

from nstaaf.config import Settings
from nstaaf.corpus import load_episode_documents
from nstaaf.indexing import require_openai_client, search_index

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "about",
    "after",
    "again",
    "being",
    "from",
    "have",
    "into",
    "just",
    "more",
    "over",
    "such",
    "that",
    "their",
    "them",
    "then",
    "they",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def format_segment_text(segment: dict[str, Any]) -> str:
    timestamp = (segment.get("timestamp") or "").strip()
    text = str(segment.get("text") or "").strip()
    if not text:
        return ""
    if timestamp:
        return f"[{timestamp}] {text}"
    return text


def token_set(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_RE.findall(value.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def candidate_lexical_score(query: str, candidate: dict[str, Any]) -> int:
    query_phrase = " ".join(query.lower().split())
    title = str(candidate.get("title") or "")
    text = str(candidate.get("candidate_text") or candidate.get("matched_text") or "")

    title_tokens = token_set(title)
    text_tokens = token_set(text)
    query_tokens = token_set(query)
    combined_tokens = title_tokens | text_tokens

    score = 0
    combined_text = f"{title.lower()} {text.lower()}".strip()
    if query_phrase and query_phrase in combined_text:
        score += 12
    score += 4 * len(query_tokens & title_tokens)
    score += 2 * len(query_tokens & text_tokens)
    if query_tokens and query_tokens <= combined_tokens:
        score += 4
    return score


def sort_candidates_for_query(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for candidate in candidates:
        candidate["lexical_score"] = candidate_lexical_score(query, candidate)
    return sorted(
        candidates,
        key=lambda candidate: (
            -int(candidate.get("lexical_score", 0)),
            float(candidate["distance"]),
            str(candidate["title"]).lower(),
        ),
    )


def build_snippet_candidates(
    settings: Settings,
    search_results: list[dict[str, Any]],
    *,
    query: str | None = None,
    context_window: int = 1,
) -> list[dict[str, Any]]:
    documents = {document["slug"]: document for document in load_episode_documents(settings)}
    candidates: list[dict[str, Any]] = []
    seen_ranges: set[tuple[str, int, int]] = set()

    for result in search_results:
        document = documents.get(result["slug"])
        if not document:
            continue

        hit_segment_index = int(result["segment_index"])
        start_index = max(0, hit_segment_index - context_window)
        end_index = min(len(document["segments"]), hit_segment_index + context_window + 1)
        range_key = (result["slug"], start_index, end_index)
        if range_key in seen_ranges:
            continue
        seen_ranges.add(range_key)

        window_segments = document["segments"][start_index:end_index]
        candidate_text = " ".join(
            part for part in (format_segment_text(segment) for segment in window_segments) if part
        ).strip()
        if not candidate_text:
            continue

        candidates.append(
            {
                "candidate_id": f"cand-{len(candidates) + 1}",
                "slug": result["slug"],
                "title": result["title"],
                "url": result["url"],
                "episode_date": result.get("episode_date"),
                "timestamp": result.get("timestamp") or document["segments"][hit_segment_index].get("timestamp"),
                "segment_index": hit_segment_index,
                "start_segment_index": start_index,
                "end_segment_index": end_index - 1,
                "distance": float(result["distance"]),
                "matched_text": result["text"],
                "candidate_text": candidate_text,
                }
            )

    if query:
        return sort_candidates_for_query(query, candidates)
    return candidates


def fallback_quote(candidate: dict[str, Any]) -> str:
    raw_quote = str(candidate.get("matched_text") or candidate.get("candidate_text") or "").strip()
    if len(raw_quote) <= 240:
        return raw_quote
    shortened = raw_quote[:237].rsplit(" ", 1)[0].rstrip()
    return f"{shortened}..."


def normalize_reason(value: Any) -> str:
    reason = " ".join(str(value or "").split()).strip()
    if reason:
        return reason
    return "Strong semantic match from the transcript corpus."


def build_citation(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "title": candidate["title"],
        "url": candidate["url"],
        "slug": candidate["slug"],
        "episode_date": candidate.get("episode_date"),
        "timestamp": candidate.get("timestamp"),
        "quote": fallback_quote(candidate),
    }


def curate_snippet_candidates(
    settings: Settings,
    *,
    query: str,
    candidates: list[dict[str, Any]],
    max_snippets: int = 3,
) -> dict[str, Any]:
    if not candidates:
        return {
            "query": query,
            "model": settings.snippet_model,
            "selection_mode": "empty",
            "candidate_count": 0,
            "snippets": [],
        }

    client = require_openai_client(settings)
    prompt_payload = {
        "query": query,
        "max_snippets": max_snippets,
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "title": candidate["title"],
                "episode_date": candidate.get("episode_date"),
                "timestamp": candidate.get("timestamp"),
                "distance": round(candidate["distance"], 4),
                "text": candidate["candidate_text"],
            }
            for candidate in candidates
        ],
    }

    response = client.chat.completions.create(
        model=settings.snippet_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You select grounded podcast transcript snippets. "
                    "Use only the provided candidates. "
                    "Return JSON with a single key named snippets. "
                    "Each item must include candidate_id, quote, and reason. "
                    "quote must be copied verbatim from the candidate text, stay under 240 characters, "
                    "and should feel interesting, vivid, or directly relevant to the query."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=True, indent=2),
            },
        ],
    )

    raw_content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        parsed = {"snippets": []}

    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    snippets: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()
    seen_locations: set[tuple[str | None, str | None]] = set()

    for item in parsed.get("snippets", []):
        candidate_id = str(item.get("candidate_id") or "").strip()
        candidate = candidates_by_id.get(candidate_id)
        if not candidate or candidate_id in seen_candidate_ids:
            continue
        location_key = (candidate.get("episode_date"), candidate.get("timestamp"))
        if location_key in seen_locations:
            continue

        quote = str(item.get("quote") or "").strip()
        if not quote or quote not in candidate["candidate_text"] or len(quote) > 240:
            quote = fallback_quote(candidate)

        snippets.append(
            {
                "candidate_id": candidate_id,
                "title": candidate["title"],
                "url": candidate["url"],
                "slug": candidate["slug"],
                "episode_date": candidate.get("episode_date"),
                "timestamp": candidate.get("timestamp"),
                "distance": candidate["distance"],
                "quote": quote,
                "reason": normalize_reason(item.get("reason")),
            }
        )
        seen_candidate_ids.add(candidate_id)
        seen_locations.add(location_key)
        if len(snippets) >= max_snippets:
            break

    if snippets:
        selection_mode = "llm"
    else:
        selection_mode = "fallback"
        snippets = []
        for candidate in candidates:
            location_key = (candidate.get("episode_date"), candidate.get("timestamp"))
            if location_key in seen_locations:
                continue
            snippets.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "title": candidate["title"],
                    "url": candidate["url"],
                    "slug": candidate["slug"],
                    "episode_date": candidate.get("episode_date"),
                    "timestamp": candidate.get("timestamp"),
                    "distance": candidate["distance"],
                    "quote": fallback_quote(candidate),
                    "reason": "Top semantic hit selected without LLM curation.",
                }
            )
            seen_locations.add(location_key)
            if len(snippets) >= max_snippets:
                break

    return {
        "query": query,
        "model": settings.snippet_model,
        "selection_mode": selection_mode,
        "candidate_count": len(candidates),
        "snippets": snippets,
    }


def normalize_query_fit(value: Any) -> str:
    fit = str(value or "").strip().lower()
    if fit in {"strong", "mixed", "weak"}:
        return fit
    return "mixed"


def synthesize_facts(
    settings: Settings,
    *,
    query: str,
    candidates: list[dict[str, Any]],
    max_facts: int = 3,
) -> dict[str, Any]:
    if not candidates:
        return {
            "query": query,
            "model": settings.snippet_model,
            "selection_mode": "empty",
            "candidate_count": 0,
            "query_fit": "weak",
            "fit_reason": "No transcript candidates were retrieved for this query.",
            "facts": [],
        }

    client = require_openai_client(settings)
    prompt_payload = {
        "query": query,
        "max_facts": max_facts,
        "candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "title": candidate["title"],
                "episode_date": candidate.get("episode_date"),
                "timestamp": candidate.get("timestamp"),
                "distance": round(candidate["distance"], 4),
                "lexical_score": int(candidate.get("lexical_score", 0)),
                "text": candidate["candidate_text"],
            }
            for candidate in candidates
        ],
    }

    response = client.chat.completions.create(
        model=settings.snippet_model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You answer podcast transcript search queries using only supplied transcript excerpts. "
                    "Return JSON with keys query_fit, fit_reason, and facts. "
                    "query_fit must be one of strong, mixed, weak. "
                    "Each fact item must include fact and candidate_ids. "
                    "fact should be a concise stand-alone claim, ideally one sentence, and directly supported by the cited candidates. "
                    "candidate_ids must be an array of one to three candidate ids from the provided excerpts. "
                    "If the retrieved evidence is weak or off-topic, say so and return fewer facts. "
                    "Do not invent or clean up unclear transcript claims beyond what the excerpts support."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prompt_payload, ensure_ascii=True, indent=2),
            },
        ],
    )

    raw_content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        parsed = {}

    candidates_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    facts: list[dict[str, Any]] = []
    seen_facts: set[str] = set()

    for item in parsed.get("facts", []):
        fact_text = " ".join(str(item.get("fact") or "").split()).strip()
        if not fact_text:
            continue

        normalized_fact = fact_text.lower()
        if normalized_fact in seen_facts:
            continue

        raw_candidate_ids = item.get("candidate_ids") or item.get("source_candidate_ids") or []
        if isinstance(raw_candidate_ids, str):
            raw_candidate_ids = [raw_candidate_ids]

        citations: list[dict[str, Any]] = []
        seen_candidate_ids: set[str] = set()
        for raw_candidate_id in raw_candidate_ids:
            candidate_id = str(raw_candidate_id).strip()
            candidate = candidates_by_id.get(candidate_id)
            if not candidate or candidate_id in seen_candidate_ids:
                continue
            citations.append(build_citation(candidate))
            seen_candidate_ids.add(candidate_id)
            if len(citations) >= 3:
                break

        if not citations:
            continue

        facts.append(
            {
                "fact": fact_text,
                "citations": citations,
            }
        )
        seen_facts.add(normalized_fact)
        if len(facts) >= max_facts:
            break

    selection_mode = "llm"
    if not facts:
        selection_mode = "fallback"
        for candidate in candidates[:max_facts]:
            facts.append(
                {
                    "fact": fallback_quote(candidate),
                    "citations": [build_citation(candidate)],
                }
            )

    return {
        "query": query,
        "model": settings.snippet_model,
        "selection_mode": selection_mode,
        "candidate_count": len(candidates),
        "query_fit": normalize_query_fit(parsed.get("query_fit")),
        "fit_reason": normalize_reason(parsed.get("fit_reason") or parsed.get("reason")),
        "facts": facts,
    }


def generate_snippet_report(
    settings: Settings,
    *,
    query: str,
    top_k: int = 8,
    max_snippets: int = 3,
    context_window: int = 1,
) -> dict[str, Any]:
    search_results = search_index(settings, query=query, top_k=max(top_k, max_snippets))
    candidates = build_snippet_candidates(
        settings,
        search_results,
        query=query,
        context_window=context_window,
    )
    report = curate_snippet_candidates(
        settings,
        query=query,
        candidates=candidates,
        max_snippets=max_snippets,
    )
    report["retrieval_top_k"] = max(top_k, max_snippets)
    return report


def generate_fact_report(
    settings: Settings,
    *,
    query: str,
    top_k: int = 12,
    max_facts: int = 3,
    context_window: int = 2,
) -> dict[str, Any]:
    retrieval_top_k = max(top_k, max_facts * 4)
    search_results = search_index(settings, query=query, top_k=retrieval_top_k)
    candidates = build_snippet_candidates(
        settings,
        search_results,
        query=query,
        context_window=context_window,
    )
    report = synthesize_facts(
        settings,
        query=query,
        candidates=candidates[:retrieval_top_k],
        max_facts=max_facts,
    )
    report["retrieval_top_k"] = retrieval_top_k
    return report
