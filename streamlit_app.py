from __future__ import annotations

import streamlit as st

from nstaaf.config import get_settings
from nstaaf.corpus import status_snapshot
from nstaaf.indexing import search_index
from nstaaf.snippets import build_snippet_candidates, curate_snippet_candidates, synthesize_facts


st.set_page_config(page_title="NSTAAF Search", page_icon=":mag:", layout="wide")

settings = get_settings()
status = status_snapshot(settings)

st.title("NSTAAF Transcript Search")
st.caption("Local semantic search over the cleaned No Such Thing As A Fish transcript corpus.")

left, right = st.columns([2, 1])
with left:
    query = st.text_input("Search query", value="mexico avocado")
with right:
    top_k = st.slider("Results", min_value=1, max_value=20, value=5)

llm_mode = st.selectbox(
    "Answer style",
    options=["Synthesized facts", "Supporting quotes", "Raw search only"],
    index=0,
    help=(
        "Synthesized facts gives you 1-3 grounded claims with citations. "
        "Supporting quotes gives you the best transcript excerpts. "
        "Raw search only shows the retrieved chunks without LLM synthesis."
    ),
)

with st.expander("Corpus status", expanded=False):
    st.json(status)

if st.button("Search", type="primary") and query.strip():
    with st.spinner("Searching the local index..."):
        try:
            retrieval_top_k = top_k
            if llm_mode == "Synthesized facts":
                retrieval_top_k = max(top_k, 12)
            elif llm_mode == "Supporting quotes":
                retrieval_top_k = max(top_k, 8)

            results = search_index(settings, query=query.strip(), top_k=retrieval_top_k)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
        else:
            if not results:
                st.info("No results found.")
            else:
                if llm_mode == "Synthesized facts":
                    try:
                        fact_report = synthesize_facts(
                            settings,
                            query=query.strip(),
                            candidates=build_snippet_candidates(
                                settings,
                                results,
                                query=query.strip(),
                                context_window=2,
                            ),
                            max_facts=min(3, top_k),
                        )
                    except Exception as exc:  # noqa: BLE001
                        st.warning(f"Fact synthesis failed: {exc}")
                    else:
                        st.subheader("Synthesized facts")
                        st.caption(f"LLM: {fact_report['model']}")
                        if fact_report["query_fit"] == "weak":
                            st.warning(f"Query fit looks weak: {fact_report['fit_reason']}")
                        elif fact_report["query_fit"] == "mixed":
                            st.info(f"Query fit is mixed: {fact_report['fit_reason']}")
                        else:
                            st.caption(fact_report["fit_reason"])

                        for index, fact in enumerate(fact_report["facts"], start=1):
                            st.markdown(f"**{index}. {fact['fact']}**")
                            for citation in fact["citations"]:
                                st.caption(
                                    " | ".join(
                                        part
                                        for part in [
                                            citation["title"],
                                            citation.get("episode_date") or "Unknown date",
                                            citation.get("timestamp") or "No timestamp",
                                        ]
                                        if part
                                    )
                                )
                                st.markdown(f"[Source episode]({citation['url']})")
                                with st.expander(f"Evidence: {citation['candidate_id']}"):
                                    st.write(citation["quote"])

                        st.divider()

                elif llm_mode == "Supporting quotes":
                    try:
                        snippet_report = curate_snippet_candidates(
                            settings,
                            query=query.strip(),
                            candidates=build_snippet_candidates(
                                settings,
                                results,
                                query=query.strip(),
                                context_window=1,
                            ),
                            max_snippets=min(5, top_k),
                        )
                    except Exception as exc:  # noqa: BLE001
                        st.warning(f"Snippet curation failed: {exc}")
                    else:
                        if snippet_report["snippets"]:
                            st.subheader("Supporting quotes")
                            st.caption(f"LLM: {snippet_report['model']}")
                            for snippet in snippet_report["snippets"]:
                                st.markdown(f"**{snippet['title']}**")
                                st.caption(
                                    " | ".join(
                                        part
                                        for part in [
                                            snippet.get("episode_date") or "Unknown date",
                                            snippet.get("timestamp") or "No timestamp",
                                            f"distance={snippet['distance']:.4f}",
                                        ]
                                        if part
                                    )
                                )
                                st.write(snippet["quote"])
                                st.caption(snippet["reason"])
                                st.markdown(f"[Source episode]({snippet['url']})")

                            st.divider()

                with st.expander("Raw semantic hits", expanded=llm_mode == "Raw search only"):
                    for result in results[:top_k]:
                        st.subheader(f"{result['rank']}. {result['title']}")
                        st.caption(
                            " | ".join(
                                part
                                for part in [
                                    result.get("episode_date") or "Unknown date",
                                    result.get("timestamp") or "No timestamp",
                                    f"distance={result['distance']:.4f}",
                                ]
                                if part
                            )
                        )
                        st.write(result["text"])
                        st.markdown(f"[Source episode]({result['url']})")
                        st.code(result["transcript_path"], language="text")
