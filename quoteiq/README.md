# QuoteIQ

An example app on Abenix: request-for-quotation (RFQ) emails for a fluoropolymer wire and cable manufacturer. For each email, Abenix reads the RFQ lines, finds each line's product in a mock ERP, and drafts a quote or a clarification for a person to review, or escalates the RFQ to staff. No draft reaches a customer without a person approving it.

The showcase is product search. Customers write loosely: military part numbers (`M22759/16-22-9`), shorthand (`600V 7/0.16 OD 1.1 BLK, Wht, Red, Grn`) or a plain-language specification. An agent turns each line into a structured ERP query, and a code asset does the search and the price arithmetic, so no price comes from the model.

## How it works

| Piece | What it does |
|---|---|
| Pipeline `quoteiq-rfq` | Four agents: the extractor splits the email into RFQ lines, the product matcher searches the ERP once per line (a `for_each` step, so each line's search can be opened in the run view), the decider chooses quote, clarification or escalation, and the drafter writes the reply |
| Code asset `quoteiq-erp-query` | The mock ERP: a catalogue of 127 products in `products.csv`, with search, pricing (MoQ, quantity breaks) and lead times. See [code-assets/erp-query](code-assets/erp-query/README.md) |
| `api/` | FastAPI on port 8008. Holds the inbox, starts a run per email, follows it, and raises an Abenix approval for every draft |
| `web/` | Next.js on port 3008. The inbox, and a page per email with its lines, how each was matched, the draft and the review |

Every draft is an Abenix approval, and the reviewer's three choices map onto its three decisions:

| Reviewer chooses | Approval decision | What happens |
|---|---|---|
| Send | Approve | The email is recorded as sent. Nothing is mailed, as this is an example |
| Ask the customer | Return for changes, with a note | The drafter writes a new clarification from the note and the RFQ's line results, and it comes back for review |
| Escalate | Deny, with a note | Nothing is sent. Staff take the RFQ over |

A decision made on Abenix's own Approvals page counts too: the API checks open approvals every 10 seconds.

```
quoteiq/
  api/           FastAPI on :8008. app/core (store, runs, reviews), app/routers, tests, sdk (vendored)
  web/           Next.js on :3008. / (inbox), /emails/[id] (one email)
  code-assets/   erp-query: the mock ERP and its catalogue
  scripts/       generate_products.py (the catalogue), verify_seed_data.py, evaluate_pipeline.py
  test-data/     emails/ (seven example RFQs), expected-outcomes.json
```

The agents and the pipeline are seeded from `packages/db/seeds/agents/qq_*.yaml`.

## Running it locally

You need a local Abenix with an LLM provider key in `.env`. See [Required env vars](../docs/08-howto/00-local-setup.md#required-env-vars). The agents use `claude-sonnet-4-5-20250929`.

### The quick way

```bash
APPS=quoteiq bash scripts/dev-local.sh
```

This starts the platform (API on :8000, web on :3000) and QuoteIQ with it. It seeds the four QuoteIQ agents and the `quoteiq-rfq` pipeline, creates QuoteIQ's API key (`standalone-quoteiq`, with the `can_delegate` scope) and hands it to [`start.sh`](start.sh), which seeds the ERP code asset and starts the API on :8008 and the web app on :3008. Logs go to `quoteiq/logs/`. Without `APPS`, `dev-local.sh` asks which apps to start. See [Choosing which use-case apps to start](../docs/08-howto/00-local-setup.md#choosing-which-use-case-apps-to-start).

Then open http://localhost:3008.

Press **Process next RFQ email** to send the oldest waiting email to the pipeline, or tick emails in the list and press **Process selected**. An email's own page has a **Process** button too. Several can run side by side. Open an email to watch its run: the step tracker counts the lines searched, and the lines, their prices and the draft appear when the run finishes. Each line's **How it was matched** shows what the matcher understood, the filters it sent to the ERP and what came back. Then edit the draft if you like, and **Send**, **Ask the customer…** or **Escalate…**. **Reset example**, in the menu at the top right, clears every result. ← and → move between emails.

With a `DATABASE_URL` in `.env`, the inbox is kept in Postgres (table `qq_emails`): results survive a restart, and a run still going when the API stopped is picked up again.

`bash quoteiq/start.sh` restarts QuoteIQ alone. It reads `.env`, so on its own it needs `QUOTEIQ_ABENIX_API_KEY` there (step 3 below).

### Running the pieces yourself

#### 1. Start Abenix

```bash
bash scripts/dev-local.sh
```

This starts the platform on http://localhost:8000 (web on :3000) and seeds the agents, including the four QuoteIQ agents and the `quoteiq-rfq` pipeline. See [Path B: processes on your machine](../docs/08-howto/00-local-setup.md#path-b-processes-on-your-machine), and [Required env vars](../docs/08-howto/00-local-setup.md#required-env-vars) for the LLM key in `.env`. The agents use `claude-sonnet-4-5-20250929`.

#### 2. Seed the ERP code asset

`dev-local.sh` doesn't seed code assets, so run the seeder once, from the repository root, with the same `DATABASE_URL` the platform uses (the default below is dev-local's, so set yours if your `.env` has another):

```bash
CODE_ASSET_STORE="$PWD/.data/code-assets" python packages/db/seeds/seed_code_assets.py
```

It is idempotent. It packages every app's code assets, `quoteiq-erp-query` among them. To check the catalogue itself, offline:

```bash
python3 quoteiq/scripts/verify_seed_data.py
```

#### 3. Give the API a key

The API calls Abenix with its own key, `QUOTEIQ_ABENIX_API_KEY`. The key needs the `can_delegate` scope, because the API runs the pipeline on behalf of the reviewer (the acting user, `X-Abenix-Subject`).

`dev-local.sh` creates a key for each app it starts and gives it only to that app's process, so for the API you start yourself, create a key and keep it in `.env`:

1. Create a key, signed in as `admin@abenix.dev` (see [Default logins](../docs/08-howto/00-local-setup.md#default-logins)): on the **API Keys** page (`/settings/api-keys`), or with `POST /api/api-keys`. See [API keys in the REST reference](../docs/09-reference/00-rest-api.md#api-keys), or [API keys in the Python SDK](../docs/03-sdk/01-python.md#api-keys). The secret is shown once.
2. Give it the `can_delegate` scope. The API Keys page doesn't set scopes, so either create the key with `"scopes": {"can_delegate": true}` or add the scope afterwards with `PATCH /api/api-keys/{key_id}`. Why the scope is needed: [Who is allowed to delegate](../docs/01-architecture/01-tenants-rbac.md#who-is-allowed-to-delegate).
3. Add it to `.env` at the repository root:

   ```bash
   QUOTEIQ_ABENIX_API_KEY=af_...
   ```

   `.env` is git-ignored. On each start `dev-local.sh` checks this key and keeps it while it is valid, instead of replacing it.

#### 4. Start the API

```bash
cd quoteiq/api
pip install -r requirements.txt
export QUOTEIQ_ABENIX_API_KEY=af_...      # the key from step 3
PYTHONPATH=.:sdk python main.py
```

Check that it can reach Abenix:

```bash
curl -s localhost:8008/api/qq/platform
```

`reachable`, `pipeline_registered` and `drafter_registered` should all be `true`. If not, `detail` says why. The interactive API is at http://localhost:8008/docs.

#### 5. Start the web app

In another terminal:

```bash
cd quoteiq/web
npm install
npm run dev
```

Open http://localhost:3008. It reaches the API through `/api/qq` (set `QUOTEIQ_API_INTERNAL_URL` if the API isn't on `localhost:8008`).

### In a local cluster

```bash
APPS=quoteiq bash scripts/deploy.sh local          # this app only
bash scripts/seed-standalone-keys.sh quoteiq       # mint its Abenix API key
```

The deploy seeds the agents and the ERP code asset, and forwards http://localhost:3008 and :8008. The inbox is kept in the platform's Postgres.

### Or drive the API directly

The inbox holds the seven emails in `test-data/emails/`, in file order. Each call to `process-next` sends the next waiting email to the pipeline, and `POST /api/qq/emails/{id}/process` sends a chosen one. Several can run side by side.

```bash
curl -s -X POST localhost:8008/api/qq/process-next                # 202, the run starts
curl -s localhost:8008/api/qq/stats                                # totals and the count of each status
curl -s localhost:8008/api/qq/emails                               # one row per email
curl -s localhost:8008/api/qq/emails/02-jss-part-number-no-quantity  # lines, draft, review, history, run link
```

A run takes 30 to 60 seconds. Example 1, with 13 lines, takes longer. While it runs, the email shows the step it is on and how many lines have been searched. `run_url` opens the run in Abenix, where each line's search and its ERP calls can be opened.

Then review a draft:

```bash
E=localhost:8008/api/qq/emails/02-jss-part-number-no-quantity
curl -s -X POST $E/review -H 'content-type: application/json' -d '{"action": "send"}'
curl -s -X POST $E/review -H 'content-type: application/json' -d '{"action": "ask", "note": "Ask whether white is the only colour needed"}'
curl -s -X POST $E/review -H 'content-type: application/json' -d '{"action": "escalate", "note": "We cannot make this OD"}'
```

A draft can be edited before it is sent (`PUT $E/draft`, with `subject`, `greeting`, `body` and `closing`), and reverted (`DELETE $E/draft/edits`). An edit that names a SKU is refused (422), and so is an edit while the draft's decision is being signed (409). A System error can be retried (`POST $E/retry`), and an expired review raised again (`POST $E/raise-review`). `POST /api/qq/reset` clears every result and denies any review still open in Abenix.

## The example emails

| Email | What it tests | Expected |
|---|---|---|
| 01 | Shorthand, one line per colour, a twisted-pair cable with no quantity | Quote, 13 lines |
| 02 | A JSS part number, no quantity | Quote at the minimum order quantity |
| 03 | M22759/16 part numbers | Quote, 8 lines |
| 04 | JSS part numbers below the minimum order quantity | Quote, each line raised to the MoQ with a note |
| 05 | A plain-language high-voltage spec at four quantities | Quote, 2 lines with quantity breaks |
| 06 | A specification with no size or colour | Clarification, offering the sizes and colours on offer |
| 07 | A good line, a broken ERP record, a size not made | Escalated, with the record's SKU and the nearest sizes |

`test-data/expected-outcomes.json` has each line's expected outcome and each reply's expected greeting.

## Configuration

| Variable | Default | |
|---|---|---|
| `QUOTEIQ_ABENIX_API_KEY` | none | Required, with the `can_delegate` scope |
| `ABENIX_API_URL` | `http://localhost:8000` | |
| `ABENIX_WEB_URL` | `http://localhost:3000` | For the links to runs |
| `QQ_STAFF_NAME` | `Priya Shah` | The app has no sign-in. This person signs the emails, is the acting user on every run, and is named as the reviewer |
| `QQ_PIPELINE_SLUG` | `quoteiq-rfq` | |
| `QQ_DRAFTER_SLUG` | `quoteiq-email-drafter` | Run by the API to redraft from a reviewer's note |
| `QQ_RUN_TIMEOUT_SECONDS` | `600` | A run still going after this is a System error |
| `QQ_APPROVAL_POLL_SECONDS` | `10` | How often open approvals are checked |
| `QQ_EMAILS_DIR` | `test-data/emails` | |
| `QQ_CORS_ORIGINS` | `http://localhost:3008,http://localhost:3000` | |
| `DATABASE_URL` | unset | Postgres keeps the inbox across restarts (table `qq_emails`). Unset, it lives in memory |
| `PORT` | `8008` | |

## Tests

```bash
cd quoteiq/api
pip install -r requirements.txt pytest pytest-asyncio
pytest
```

The tests use a stand-in for the Abenix SDK, so they need neither the platform nor a model.

With the app running against Abenix, a Playwright spec processes the next waiting email through the UI, checks its status and lines against `test-data/expected-outcomes.json`, and reviews it (it resets the example first if every email was processed). It skips rather than fails when the LLM provider is rate-limited or its credential is dead:

```bash
npx playwright test e2e/uat_quoteiq.spec.ts
```

To evaluate the agents themselves, `scripts/evaluate_pipeline.py` sends the example emails through the pipeline, without the app, and scores every run against `test-data/expected-outcomes.json`: the status, every line's outcome, the nearest sizes for a size not made, the recipient and greeting, no SKU in an email, and every matched line's prices against the ERP code asset's own arithmetic. It reports each email's time and cost, each line's search included. Running the emails calls the model; `--score-only` scores the saved runs again for free:

```bash
pip install -r quoteiq/api/requirements.txt
export QUOTEIQ_ABENIX_API_KEY=af_...
python3 quoteiq/scripts/evaluate_pipeline.py          # all seven, or by number: 02 07
python3 quoteiq/scripts/evaluate_pipeline.py --score-only
```

The key must be one the Abenix you run against knows. A cluster deploy mints its own key into the `quoteiq-secrets` Secret, so a key from a dev-local `.env` gets `HTTP 401: Not authenticated` there. On a cluster, take the key from the Secret:

```bash
export QUOTEIQ_ABENIX_API_KEY=$(kubectl get secret -n abenix quoteiq-secrets -o jsonpath='{.data.QUOTEIQ_ABENIX_API_KEY}' | base64 -d)
```

The web app is checked by its type check, lint and build:

```bash
cd quoteiq/web
npx tsc --noEmit && npm run lint && npm run build
```

## Known limitations

- **The reviewer in Abenix.** Approvals record the API key's account as the signer, and mark the sign-off self-approved because the same key raised it. The reviewer's name goes into the reason instead: `Reviewed by Priya Shah: <note>`.
- **Run cost.** The cost Abenix reports for a run leaves out the `for_each` step, so it misses the line searches. Each line's own cost is kept with the line.
- **Local code-asset build cache.** On a local Docker sandbox, if the first ERP call of a session works and later ones fail before the asset runs, turn the build cache off: set `CODE_ASSET_BUILD_CACHE` in `.env` to a path that can't be created, such as `/dev/null/code-asset-cache`, and restart `dev-local.sh`.
