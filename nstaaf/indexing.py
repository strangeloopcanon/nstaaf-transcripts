from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from openai import OpenAI

from nstaaf.config import Settings
from nstaaf.corpus import load_episode_documents


def split_text_into_chunks(text: str, max_chunk_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_chunk_words:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    for sentence in text.replace("\n", " ").split(". "):
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence_words = sentence.split()
        if len(sentence_words) > max_chunk_words:
            if current:
                chunks.append(" ".join(current).strip())
                current = []
            for index in range(0, len(sentence_words), max_chunk_words):
                chunks.append(" ".join(sentence_words[index : index + max_chunk_words]).strip())
            continue
        if len(current) + len(sentence_words) > max_chunk_words and current:
            chunks.append(" ".join(current).strip())
            current = sentence_words[:]
        else:
            current.extend(sentence_words)
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def require_openai_client(settings: Settings) -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to the parent Coding .env or export it first.")
    return OpenAI(api_key=settings.openai_api_key)


def iter_chunk_records(settings: Settings, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for document in load_episode_documents(settings, limit=limit):
        for segment_index, segment in enumerate(document["segments"]):
            for chunk_index, chunk in enumerate(
                split_text_into_chunks(segment["text"], max_chunk_words=settings.max_chunk_words)
            ):
                records.append(
                    {
                        "slug": document["slug"],
                        "title": document["title"],
                        "url": document["url"],
                        "episode_date": document.get("episode_date"),
                        "episode_date_iso": document.get("episode_date_iso"),
                        "timestamp": segment.get("timestamp"),
                        "segment_index": segment_index,
                        "chunk_index": chunk_index,
                        "text": chunk,
                        "transcript_path": str(settings.transcripts_dir / f"{document['slug']}.md"),
                    }
                )
    return records


def embed_text_batch(client: OpenAI, model: str, texts: list[str]) -> list[list[float]]:
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = client.embeddings.create(model=model, input=texts)
            return [item.embedding for item in response.data]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Embedding request failed after retries: {last_error}") from last_error


def build_index(settings: Settings, limit: int | None = None) -> dict[str, Any]:
    settings.ensure_directories()
    client = require_openai_client(settings)
    records = iter_chunk_records(settings, limit=limit)
    if not records:
        raise RuntimeError("No extracted episode JSON files were found. Run `nstaaf refresh` first.")

    tmp_index_path = settings.index_dir / "faiss.index.tmp"
    tmp_metadata_path = settings.index_dir / "metadata.jsonl.tmp"
    tmp_manifest_path = settings.index_dir / "manifest.json.tmp"

    index: faiss.IndexFlatL2 | None = None
    with tmp_metadata_path.open("w", encoding="utf-8") as metadata_handle:
        for start in range(0, len(records), settings.embedding_batch_size):
            batch = records[start : start + settings.embedding_batch_size]
            embeddings = embed_text_batch(client, settings.embedding_model, [record["text"] for record in batch])
            matrix = np.array(embeddings, dtype="float32")
            if index is None:
                index = faiss.IndexFlatL2(matrix.shape[1])
            index.add(matrix)
            for record in batch:
                metadata_handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    if index is None:
        raise RuntimeError("Failed to build the FAISS index.")

    faiss.write_index(index, str(tmp_index_path))
    manifest = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "embedding_model": settings.embedding_model,
        "record_count": len(records),
        "dimension": index.d,
    }
    tmp_manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    tmp_index_path.replace(settings.index_path)
    tmp_metadata_path.replace(settings.metadata_path)
    tmp_manifest_path.replace(settings.manifest_path)
    return manifest


def load_metadata(settings: Settings) -> list[dict[str, Any]]:
    if not settings.metadata_path.exists():
        raise RuntimeError("Metadata file is missing. Run `nstaaf index` first.")
    with settings.metadata_path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def search_index(settings: Settings, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    if not settings.index_path.exists():
        raise RuntimeError("FAISS index is missing. Run `nstaaf index` first.")

    client = require_openai_client(settings)
    query_embedding = np.array(
        [embed_text_batch(client, settings.embedding_model, [query])[0]],
        dtype="float32",
    )
    index = faiss.read_index(str(settings.index_path))
    metadata = load_metadata(settings)
    distances, indices = index.search(query_embedding, top_k)

    results: list[dict[str, Any]] = []
    for rank, idx in enumerate(indices[0]):
        if idx < 0:
            continue
        record = dict(metadata[idx])
        record["distance"] = float(distances[0][rank])
        record["rank"] = rank + 1
        results.append(record)
    return results
