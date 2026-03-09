from __future__ import annotations

import streamlit as st

from nstaaf.config import get_settings
from nstaaf.corpus import status_snapshot
from nstaaf.indexing import search_index


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

with st.expander("Corpus status", expanded=False):
    st.json(status)

if st.button("Search", type="primary") and query.strip():
    with st.spinner("Searching the local index..."):
        try:
            results = search_index(settings, query=query.strip(), top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
        else:
            if not results:
                st.info("No results found.")
            for result in results:
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
