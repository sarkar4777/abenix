# Changelog


## v1.0.0 — 2026-04-30

### Added
- Atlas — unified ontology + KB canvas with 4 agent tools (`atlas_describe`, `atlas_query`, `atlas_traverse`, `atlas_search_grounded`); 5 starter ontologies; semantic / circle / grid layouts; visual query; ghost-cursor suggestions; time-slider snapshots; JSON-LD export.
- BPM Analyzer — multimodal end-to-end (PDF / image / audio / video / DOCX / text), provider-native JSON modes, beautifully formatted PDF download.
- Visual user guide at `/help` — categorised sidebar TOC, every feature covered with a screenshot, dedicated sections on Atlas / NATS scaling / RUNTIME_MODE / multi-tenancy.
- Versioned public-publish flow with `RELEASE_NOTES_PENDING.md` accumulator + `CHANGELOG.md` archive.
- Self-healing pipelines — failed nodes are auto-diagnosed and retried with a corrected input/config; a single Pipeline Operations category in `/help` documents the contract; user-visible "Auto-fix applied" entries in `/executions`.
- Workflow shell — typed verb grammar (`run`, `inspect`, `retry`, `branch`, `gate`) and a REPL UI inside the pipeline detail view; chat with a pipeline like a programmable surface, with full execution history and tool-call traces.
- Per-agent dedicated pod scaling — four pools (`default`, `chat`, `heavy-reasoning`, `long-running`), KEDA queue-depth-based autoscaling per pool, admin UI at `/admin/scaling` with cost projection and live replica counts.

### Changed
- Settings → Security: removed unimplemented 2FA tile; rebuilt activity log with per-action icons + summaries; loopback IPs render as "internal".
- README: differentiator-led structure, mermaid diagrams (architecture · NATS scaling · pipeline showcase), 11-row enterprise-ready matrix.
- Sidebar: deduplicated Moderation / Alerts / All-Executions entries; reframed SDK Playground TS-disabled tooltip.
- Agent runtime: per-pool isolation so a runaway long-running job no longer starves the chat pool.

### Fixed
- BPM Analyzer agent-spec parser — robust to JS-style comments, smart quotes, fenced JSON, trailing commas; auto-retries with provider-native JSON mode on the user's chosen model (no hardcoded fallback).
- Multi-tenancy story documented end-to-end (auto-on-signup; team invites; per-user quotas; per-feature flags; ResourceShare; actAs delegation).
- ClaimsIQ runtime: Vaadin defaults to production mode at startup so the Spring Boot fat-JAR no longer scans for a Maven/Gradle project directory.
- Pipeline engine: 7 multi-agent traps closed (type:agent DSL, auto-deps from templates, agent_step `{response}` unwrap, fenced-JSON + trailing-prose parsing, targeted input fallback, db_url wiring, inline path returning final_output).
