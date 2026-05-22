# ContractIQ

**PPA & Gas Contract Intelligence Platform** — built on Abenix.

ContractIQ is a standalone application for analyzing energy contracts (Power Purchase Agreements, Gas Supply Agreements, Tolling Agreements, Virtual PPAs). It uses the Abenix SDK for AI-powered features (extraction, analysis, chat, knowledge graph).

## Architecture

```
contractiq/
├── api/                    # Standalone FastAPI backend (port 8001)
│   ├── main.py             # Entry point
│   ├── app/
│   │   ├── routers/        # auth, contracts, analysis (no Abenix dependency)
│   │   ├── models/         # SQLAlchemy models (own contractiq_* tables)
│   │   ├── core/           # deps, responses, market_cache, extraction_schemas
│   ├── sdk/                # Duplicated Abenix SDK
│   │   └── abenix_sdk/
│   └── requirements.txt
├── web/                    # Next.js frontend (port 3001)
│   └── src/app/            # Pages: dashboard, contracts, chat, market, etc.
├── test-contracts/         # Sample contracts for testing
├── start.sh                # Standalone launch script
└── README.md
```

## Dependencies

- **Database**: shared PostgreSQL with Abenix (uses `contractiq_*` tables only)
- **Abenix**: required for AI features (chat, extraction agents, knowledge graph)
- **Abenix API key**: must have `can_delegate` scope for actAs delegation

## Authentication

ContractIQ has its own user system (separate from Abenix):
- ContractIQ users register/login via `/api/contractiq/auth/`
- ContractIQ JWT auth used internally
- Calls to Abenix use a single platform API key + actAs delegation

## How it talks to Abenix

ContractIQ holds **one** Abenix platform API key. Every chat call:

1. ContractIQ user logs in → ContractIQ JWT
2. ContractIQ chat endpoint receives request
3. Constructs `ActingSubject(subject_type="contractiq", subject_id=user.id, ...)`
4. Calls `forge.execute("contractiq-chat", message, act_as=subject)` via SDK
5. SDK sends `X-Abenix-Subject` header with the user identity
6. Abenix enforces RBAC based on the acting subject (subject_policies table)
7. Tools like `portfolio_contractiq` filter data by `subject_id`

## Running

### Standalone

```bash
cd contractiq
bash start.sh
```

### As part of the full stack

The main `scripts/dev-local.sh` automatically chains to ContractIQ after Abenix is up.

## Required Environment Variables

```bash
# Database (shared with Abenix)
DATABASE_URL=postgresql://abenix:abenix@localhost:5432/abenix

# Abenix SDK access
ABENIX_API_URL=http://localhost:8000
CONTRACTIQ_ABENIX_API_KEY=af_ciq_...    # platform key with can_delegate scope

# Contract extraction (LLM)
ANTHROPIC_API_KEY=sk-ant-...

# ContractIQ JWT
CONTRACTIQ_JWT_SECRET=your-secret-here
```

## Features

- **Multi-pass extraction**: 100+ fields per contract type (PPA, Gas, Tolling, VPPA)
- **AI Chat**: 8 tools (portfolio, knowledge graph, market data, calculator)
- **Knowledge Graph**: entities & relationships via Cognify
- **Market Monitoring**: live ENTSO-E, Ember, ECB data with PnL/MTM
- **Comparison**: side-by-side, risk matrix radar, financial analysis
- **Full RBAC**: each user only sees their own data via actAs delegation
