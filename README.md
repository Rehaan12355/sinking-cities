# Sinking Cities

**NASA Space Apps Challenge 2026 · Seattle · "Dancing with the SARs"**

Sinking Cities uses NASA radar to show which parts of a US coastal city are quietly
sinking, roughly when those areas could start flooding regularly, and how many people
live there, so leaders can protect people before it happens.

Study area: Norfolk and Hampton Roads, Virginia.

## How it is put together

- `pipeline/`: Python steps that download public data and precompute everything.
- `site/`: a static website (no server, no login) that reads the precomputed files in `site/data/`.
- `DATA_SOURCES.md`: every file's URL, retrieval date, size and licence.

Work in progress: this README is filled in as each build step passes its check.

## AI disclosure

This project was built with help from Claude (Anthropic) for code and text drafting.
All data comes from the public sources listed in `DATA_SOURCES.md`; no values are AI-generated.
