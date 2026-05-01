# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Email the maintainers at `security@abenix.dev` (or the primary maintainer listed in the GitHub org). Encrypt with our PGP key if the issue involves credentials or PII.

You can expect:

- Acknowledgement within 72 hours.
- An initial assessment within one week.
- A coordinated disclosure timeline if the issue is confirmed (typically 30–90 days).

## Scope

In scope:
- The published Helm chart, Docker images, and the code in this repo (`apps/`, `packages/`, `infra/`, `scripts/`).
- The default deployment configuration.

Out of scope:
- Self-hosted deployments running custom forks.
- Findings that require root on the cluster the platform runs on.
- LLM provider quirks (report those to the provider).

## Threat model summary

Abenix runs in trusted network boundaries. The default deploy assumes:

- Postgres and Redis are not exposed publicly.
- The agent-runtime sandbox is the boundary between user code and the cluster — escapes are critical.
- Tenant isolation is enforced per row at every read; bypasses are critical.
- API keys are bcrypt-hashed at rest; plaintext exposure is critical.

If you find anything that breaches one of those assumptions, that's a critical issue.
