# Screenshots

Capture screenshots into this directory at the filenames below. The README and the in-app help guide reference these names.

Capture them at **2× DPI** (looks crisp on retina) and roughly **1600×900** for hero shots, **1200×750** for detail shots. Drop the entire window — sidebar, toolbar, content area — so users can map what they see in the screenshot to what they see in the app.

## Required hero captures

| Filename | What to capture |
|---|---|
| `01-dashboard.png` | The Dashboard page with at least 5 agents, recent executions, and the cost chart populated. |
| `02-agent-builder.png` | The Agent Builder pipeline canvas with 3+ nodes wired up and a tool/KB attached. |
| `03-bpm-analyzer.png` | The BPM Analyzer mid-conversation, showing the rendered markdown analysis with a table. |
| `04-atlas-canvas.png` | The Atlas canvas after importing FIBO Core — ~10 nodes connected with cardinality labels visible. |
| `05-atlas-empty-state.png` | The Atlas onboarding panel (empty canvas with the four start cards). |
| `06-atlas-extract.png` | The Atlas drop overlay during file extraction, with the proposed-ops ribbon at the bottom. |
| `07-knowledge-bases.png` | A Knowledge Base detail page showing graph statistics and a few documents. |
| `08-alerts-page.png` | The /alerts page grouping failures by failure_code. |
| `09-grafana-dashboard.png` | The bundled Grafana "Abenix Operations" dashboard. |

## Detail captures referenced by the user guide

| Filename | What to capture |
|---|---|
| `detail-tool-call.png` | A chat message expanded to show a tool call and its arguments + result. |
| `detail-pipeline-trace.png` | A pipeline execution detail page showing per-step timings. |
| `detail-atlas-inspector.png` | The Atlas right-rail inspector with the Schema / Relations / Properties / Instances / Lineage tabs visible. |
| `detail-atlas-suggestions.png` | The Atlas ghost-cursor card with at least 2 suggestions visible. |
| `detail-mcp-config.png` | The MCP server configuration page with at least one server registered. |
| `detail-trigger-config.png` | The Triggers page with a cron + webhook trigger configured. |

## Capture tips

- Sign in as `admin@abenix.dev` (the seeded admin) so the badge shows "admin" not your personal name.
- Use the dark theme (it's the default).
- Use Chrome's device-toolbar at 1.5× scale for crisp output.
- Crop to the browser window only — no OS chrome, no taskbar.
