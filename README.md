# NSTAAF

A simple, reusable transcript pipeline for No Such Thing As A Fish:

- discover the latest Podscripts episode URLs
- download missing transcript pages
- extract clean transcript files into `corpus/`
- build a local FAISS index with OpenAI embeddings
- search it from the CLI or a tiny Streamlit UI
- export a static GitHub Pages site with Pagefind keyword search

The old one-off notebook and raw artifacts are left in place for reference, but the supported workflow is the package in `nstaaf/`.

## Project Layout

- `nstaaf/`: Python package
- `data/source_urls.csv`: discovered episode URLs
- `data/episodes/`: structured episode JSON
- `corpus/`: GitHub-friendly markdown transcripts
- `site_docs/`: generated MkDocs source for the public transcript site (created by `nstaaf export-site` when needed)
- `data/html/`: downloaded raw HTML
- `data/index/`: FAISS index + metadata
- `site_assets/`: tracked CSS/JS copied into the generated site docs
- `.github/workflows/pages.yml`: weekly GitHub Pages refresh and deploy workflow

## Quickstart

```bash
cd /Users/rohit/Documents/Workspace/Coding/NSTAAF
python -m venv .venv
source .venv/bin/activate
pip install -e ".[site]"
```

The code automatically looks for `.env` in this repo and in the parent Coding folder, so your existing `/Users/rohit/Documents/Workspace/Coding/.env` will be picked up for `OPENAI_API_KEY`.

## Commands

Refresh the discovered URL list:

```bash
nstaaf discover
```

Download and extract the corpus:

```bash
nstaaf refresh
```

Rebuild the embedding index:

```bash
nstaaf index
```

Run a full end-to-end refresh:

```bash
nstaaf rebuild
```

Search from the terminal:

```bash
nstaaf search "mexico avocado" --top-k 5
```

Generate a few grounded supporting quotes from the semantic hits:

```bash
nstaaf snippets "mexico avocado" --top-k 8 --max-snippets 3
```

Ask for 1-3 synthesized facts grounded in the retrieved transcript evidence:

```bash
nstaaf facts "roman revolution" --top-k 12 --max-facts 3
```

Check project status:

```bash
nstaaf status
```

Launch the local search UI:

```bash
nstaaf ui
```

Run the local web UI directly:

```bash
streamlit run /Users/rohit/Documents/Workspace/Coding/NSTAAF/streamlit_app.py
```

Use the versioned launcher script:

```bash
./scripts/launch_local_ui.command
```

Export the GitHub Pages source tree:

```bash
nstaaf export-site
```

Build the static site locally:

```bash
mkdocs build --strict
npx -y pagefind@1.4.0 --site site
python -m http.server 8000 -d site
```

`site_docs/` and `site/` are generated build artifacts. They may be absent in a lean local checkout until you run the export/build commands above.

## GitHub-Friendly Setup

If you turn this into a repo later, the easiest thing to commit is:

- `corpus/`
- `data/episodes/`
- `data/source_urls.csv`
- the package code, MkDocs config, workflow, and README

The raw HTML downloads and FAISS index are ignored because they are large and easy to regenerate.

## Public Site

The public site path is intentionally separate from the local semantic search app:

- `nstaaf export-site` generates `site_docs/` from `data/episodes/`
- MkDocs renders that into `site/`
- Pagefind adds static keyword search to the built HTML
- GitHub Actions republishes the site on pushes to `main`, on manual runs, and on the weekly refresh schedule via `.github/workflows/pages.yml`

Both `site_docs/` and `site/` are safe to delete locally after a build if you want to keep the workspace lean. They are regenerated from committed source files.

The Pages site is keyword search only. The local FAISS/OpenAI workflow remains available if you want semantic search privately.
The new `nstaaf snippets ...` and `nstaaf facts ...` flows are also local-only for now: they retrieve semantic hits, then use an LLM either to pick grounded snippets or synthesize a few grounded facts with citations so you can test the experience before deciding whether it belongs in a public product.

## Local Answer UI

The local Streamlit app is now answer-first:

- `Synthesized facts` is the default answer style and gives you 1-3 grounded claims with citations.
- `Supporting quotes` gives you the best transcript excerpts without trying to summarize them.
- `Raw search only` skips the LLM layer and just shows the retrieved transcript chunks.

The current local defaults are:

- embeddings: `text-embedding-3-small`
- answer model: `gpt-4.1-mini`

If you want to swap the answer model locally, set `NSTAAF_SNIPPET_MODEL` in your `.env`.
