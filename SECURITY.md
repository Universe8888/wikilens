# Security Policy

## Supported versions

wikilens is pre-alpha (0.x). Only the latest commit on `main` is supported for security fixes.

## Reporting a vulnerability

If you believe you've found a security issue — code execution, data exfiltration, supply-chain
weakness, or anything that would meaningfully harm a user running wikilens against their own
notes — please report it privately via
[GitHub Security Advisories](https://github.com/Universe8888/wikilens/security/advisories/new).

Please do **not** open a public issue for security reports.

## Scope

In scope:

- `wikilens` Python package and its CLI
- Ingestion, chunking, embedding, vector store, and query code paths
- Default model-download and dependency-installation behavior
- Any supply-chain concern affecting pinned dependencies

Out of scope:

- Vulnerabilities in upstream dependencies (`lancedb`, `sentence-transformers`, etc.) —
  please report those to their maintainers. If the issue is a *misuse* of the dependency
  inside wikilens, that is in scope.
- Denial of service via maliciously crafted markdown files when parsing completes in
  bounded time (the tool's job is to handle any vault content).

## Privacy posture

wikilens is designed to be local-first:

- No vault content leaves the machine during `ingest` or `query`.
- First-run model downloads fetch public model weights from Hugging Face and tokenizer
  tables from OpenAI's public CDN. No vault content is included in these requests.
- Future phases may introduce optional remote LLM calls; those will be opt-in and
  documented at the time they land.

If you find a case where vault content leaves the machine without explicit user consent,
treat it as a security issue and report it via the channel above.
