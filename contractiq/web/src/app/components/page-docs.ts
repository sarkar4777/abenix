import type { PageDoc } from './PageExplainer';

const ABENIX_KYC_AGENT = { slug: 'contractiq-kyc-screener', role: 'sanctions + PEP + adverse media + UBO + enforcement screening (15+ public lists)', status: 'seeded' as const };
const ABENIX_EXTRACTOR = { slug: 'contractiq-extractor', role: 'multi-pass PPA/contract clause extraction with self-discovering schema', status: 'seeded' as const };
const ABENIX_REFRESHER = { slug: 'ciq-counterparty-refresher', role: 'orchestrator that fans out financial + permit + rating sub-agents', status: 'seeded' as const };
const ABENIX_FIN = { slug: 'ciq-financial-extractor', role: 'pulls 5y financials from EDGAR / Companies House / Bundesanzeiger', status: 'seeded' as const };
const ABENIX_PERMIT = { slug: 'ciq-permit-checker', role: 'verifies FERC + EPA + PHMSA permits', status: 'seeded' as const };
const ABENIX_RATING = { slug: 'ciq-rating-fetcher', role: 'fetches S&P / Moody\'s / Fitch issuer ratings', status: 'seeded' as const };

const TOOL_OFAC = { name: 'ofac_sdn', role: 'US Treasury sanctions list', status: 'live-free' as const };
const TOOL_EU_SANC = { name: 'eu_sanctions', role: 'EU consolidated list', status: 'live-free' as const };
const TOOL_UN_SANC = { name: 'un_sanctions', role: 'UN Security Council list', status: 'live-free' as const };
const TOOL_OPEN_SANCTIONS = { name: 'opensanctions', role: 'aggregator across 100+ lists', status: 'live-free' as const };
const TOOL_EDGAR = { name: 'edgar_filings', role: 'SEC XBRL company-facts (5y financials)', status: 'live-free' as const };
const TOOL_FERC = { name: 'ferc_elibrary', role: 'FERC Market-Based Rate authority + filings', status: 'live-free' as const };
const TOOL_EPA = { name: 'epa_echo', role: 'EPA enforcement + Title V + NPDES + RCRA', status: 'live-free' as const };
const TOOL_PHMSA = { name: 'phmsa_lookup', role: 'US pipeline operator registry', status: 'live-free' as const };
const TOOL_CH = { name: 'companies_house', role: 'UK filings index', status: 'configurable-paid' as const };
const TOOL_BA = { name: 'bundesanzeiger_filings', role: 'German Jahresabschluss', status: 'live-free' as const };
const TOOL_SPG = { name: 'spg_ratings_api', role: 'S&P Global issuer ratings', status: 'configurable-paid' as const };
const TOOL_MOODYS = { name: 'moodys_api', role: "Moody's Investors Service", status: 'configurable-paid' as const };
const TOOL_FITCH = { name: 'fitch_connect', role: 'Fitch issuer ratings', status: 'configurable-paid' as const };

const DEMO_CAVEAT_AWAITING = 'This page shows synthesized chart shapes for layout. The ML models named below are not yet registered in the Abenix model catalogue (verify under /admin/ml-models). Production wiring requires uploading the trained pickles via Abenix → ML Models → Upload.';
const DEMO_CAVEAT_REUSE = 'This page reuses existing Abenix models (built originally for wingman). The numbers shown are layout-demo until the page is wired to call Abenix.execute() on those models with real input vectors.';

export const PAGE_DOCS: Record<string, PageDoc> = {
  '/dashboard': {
    title: 'Dashboard',
    one_liner: 'Single-screen operator home — KPIs, alerts, recent activity.',
    what_user_does: 'Land here after login. Scan total contracts, active assessments, pending alerts, recent agent executions. Click any tile to drill into the source page.',
    components: [
      { name: 'KPI strip',             what: 'Counts pulled from contractiq Postgres tables.',                                data_source: 'GET /api/contractiq/dashboard/summary',                       is_live: true },
      { name: 'Recent executions',     what: 'Live agent runs streaming from Abenix executions table.',                       data_source: 'GET /api/contractiq/executions (proxies Abenix /api/executions)', is_live: true },
      { name: 'Right rail live activity', what: 'Polls every 5s; shows every Abenix agent + ml-model invocation across the platform.', data_source: 'LiveActivityRail component → /api/contractiq-executions', is_live: true },
    ],
    abenix_models: [],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `browser → contractiq-api → Postgres (read counts)
browser → /api/contractiq-executions → contractiq-api → Abenix /api/executions/live
right rail polls every 5s; click any item → opens DagDrawer with the full execution SSE stream`,
    demo_status: 'fully-live',
  },

  '/credit-risk': {
    title: 'Counterparty Credit Risk',
    one_liner: 'Heat-map of every counterparty with a 1-100 credit score + compliance ticker.',
    what_user_does: 'Land here to see the colour of your book at a glance. Filter by risk tier (green/amber/red). Click a card to open the counterparty detail with 5-year financials, ratios, permits. Acknowledge compliance alerts.',
    components: [
      { name: 'Traffic-light heat map',    what: 'One card per counterparty, green (≥70), amber (50-69), red (<50). Click to drill into detail.', data_source: 'GET /api/contractiq/counterparties (Postgres)', is_live: true },
      { name: 'Compliance alerts ticker',  what: 'Open warnings raised by the sweeper (KYC > 180d, permit expiring < 60d, utilisation > 80%).', data_source: 'GET /api/contractiq/compliance-alerts', is_live: true },
      { name: 'Run sweep button',          what: 'Triggers POST /compliance-alerts/sweep — re-evaluates rules against current Postgres data.',     data_source: 'POST /api/contractiq/compliance-alerts/sweep',  is_live: true },
      { name: 'Data Source panel',         what: 'Lists every external source the production system reads from (OFAC, EU sanctions, FERC, S&P, etc.).', data_source: 'Static rendering of `DataSourcePanel` config',  is_live: true },
      { name: 'Assessment cards (legacy)', what: 'Per-counterparty AI risk assessment generated by contractiq-credit-risk agent on Abenix.',         data_source: 'GET /api/contractiq/insights/credit-risk/portfolio', is_live: true },
    ],
    abenix_models: [
      { slug: 'contractiq-risk-tier-predictor',   family: 'sklearn (classifier, 11 features)', status: 'registered', notes: 'Maps financial-ratio vector → tier 0-3.' },
      { slug: 'contractiq-counterparty-default',  family: 'sklearn (regressor)',               status: 'registered', notes: 'Outputs probability of default %.' },
    ],
    abenix_agents: [ABENIX_KYC_AGENT, ABENIX_REFRESHER],
    abenix_tools: [TOOL_OFAC, TOOL_EU_SANC, TOOL_UN_SANC, TOOL_OPEN_SANCTIONS],
    data_flow: `browser → contractiq-api → Postgres (counterparties, alerts)
"Run KYC" → contractiq-api → Abenix.execute("contractiq-kyc-screener") → tools fan out to OFAC / EU / UN / OpenSanctions / world-check
"Refresh from sources" → contractiq-api → Abenix.execute("ciq-counterparty-refresher") → fans out 3 specialist agents → writes back financials + permits + ratings + provenance rows`,
    demo_status: 'fully-live',
  },

  '/credit-risk/kyc': {
    title: 'KYC Standard Checks',
    one_liner: 'Run an agent-driven KYC against 15+ public sanctions + PEP + adverse-media sources.',
    what_user_does: 'Start a new KYC check for a counterparty. The agent screens OFAC, EU, UN, UK HMT, Canadian OSFI, OpenSanctions, Wikidata PEP, and adverse-media news. Result is persisted with full source provenance.',
    components: [
      { name: 'New KYC form',         what: 'Counterparty name + jurisdiction input.',                                  data_source: 'POST /api/contractiq/credit-risk/kyc',                            is_live: true },
      { name: 'In-flight KYC list',   what: 'Streaming list of running + completed KYC reports.',                       data_source: 'GET /api/contractiq/credit-risk/kyc',                             is_live: true },
      { name: 'Report detail',        what: 'Full structured report per check (sanctions, PEP, UBO, adverse media, enforcement, country risk).', data_source: 'GET /api/contractiq/credit-risk/kyc/{id}', is_live: true },
    ],
    abenix_models: [],
    abenix_agents: [ABENIX_KYC_AGENT],
    abenix_tools: [TOOL_OFAC, TOOL_EU_SANC, TOOL_UN_SANC, TOOL_OPEN_SANCTIONS],
    data_flow: `browser → contractiq-api → Abenix.execute("contractiq-kyc-screener", {legal_name, country})
agent runs in Abenix → fans out 15+ list-screening tool calls in parallel → returns structured report
contractiq-api persists to contractiq_kyc_reports + provenance row per source`,
    demo_status: 'fully-live',
  },

  '/credit-risk/counterparty/[id]': {
    title: 'Counterparty Detail (Financials · Ratios · Permits)',
    one_liner: 'Drill-into view per counterparty. 5-year statements, computed ratios + Altman Z, regulatory permits.',
    what_user_does: 'Pick a counterparty card from the heat map. Switch tabs. Click "Refresh from sources" to fire the orchestrator agent + repopulate from live filings.',
    components: [
      { name: 'Financials tab',  what: '5 years × 13 line items. Source chips link to filing accession on EDGAR / Companies House / Bundesanzeiger.', data_source: 'GET /api/contractiq/counterparties/{id}/financials', is_live: true },
      { name: 'Ratios tab',      what: 'Current ratio, quick, D/E, interest coverage, net margin, ROA, ROE, Altman Z. All deterministic from line items.', data_source: 'Computed at seed time + on refresh (no LLM)', is_live: true },
      { name: 'Permits tab',     what: 'FERC MBR / EPA Title V / PHMSA pipeline IDs with expiry + traffic-light tone.', data_source: 'GET /api/contractiq/counterparties/{id}/permits', is_live: true },
      { name: 'Refresh button',  what: 'Fires ciq-counterparty-refresher orchestrator on Abenix.',                       data_source: 'POST /api/contractiq/counterparties/{id}/refresh',  is_live: true },
      { name: 'Provenance chips',what: 'Every section links to source URL + filing accession on the originating registry.', data_source: 'GET /api/contractiq/counterparties/{id}/provenance', is_live: true },
    ],
    abenix_models: [],
    abenix_agents: [ABENIX_REFRESHER, ABENIX_FIN, ABENIX_PERMIT, ABENIX_RATING],
    abenix_tools: [TOOL_EDGAR, TOOL_FERC, TOOL_EPA, TOOL_PHMSA, TOOL_CH, TOOL_BA, TOOL_SPG, TOOL_MOODYS, TOOL_FITCH],
    data_flow: `click "Refresh from sources"
  → contractiq-api → Abenix.execute("ciq-counterparty-refresher")
  → orchestrator fans out 3 specialists in parallel:
       - ciq-financial-extractor → edgar_filings (or companies_house / bundesanzeiger by country)
       - ciq-permit-checker      → ferc_elibrary, epa_echo, phmsa_lookup
       - ciq-rating-fetcher      → spg_ratings_api / moodys_api / fitch_connect
  → each writes back via contractiq-api, emitting one contractiq_data_provenance row per field
  → browser polls + re-renders cells with fresh "Source · timestamp" badges`,
    demo_status: 'fully-live',
    demo_caveat: 'Initial seed contains static demo values for the 12 well-known counterparties. The Refresh button replaces those values with live filings (free sources) or asks for an API key (S&P / Moody\'s / Fitch). Numbers are never invented.',
  },

  '/forecaster': {
    title: 'Predictive Offtake Forecaster',
    one_liner: 'ML demand models for residential, industrial, storage-cycling surfaces with live what-if sliders.',
    what_user_does: 'Pick a demand surface. Drag the temperature / demand-shock / churn sliders. The fan chart and SHAP drivers should redraw in real time. Click a scenario card to lock in pre-baked stress shocks.',
    components: [
      { name: 'Surface picker',       what: 'Residential / Industrial / Storage-cycling tabs.',                             data_source: 'static UI tabs',                              is_live: true },
      { name: '14-day fan chart',     what: 'P10 / P50 / P90 of forecasted offtake.',                                       data_source: 'CURRENTLY synthesized in-browser (fanCurve())', is_live: false },
      { name: 'Live what-if sliders', what: 'Temperature, demand shock, churn. UI math redraws curve.',                     data_source: 'in-browser only — does not call Abenix yet',  is_live: false },
      { name: 'Top drivers (SHAP)',   what: 'Bar chart of feature contributions.',                                          data_source: 'static array — needs real shap_explainer call',is_live: false },
      { name: 'Pre-baked scenarios',  what: 'Four scenario cards (cold-snap, industrial pull-back, retail churn, mild winter).', data_source: 'static',                                  is_live: false },
    ],
    abenix_models: [
      { slug: 'offtake_residential',      family: 'Prophet + XGBoost (HDD/CDD + calendar + churn)', status: 'missing', notes: 'Train + register on ENTSO-E load history; output GWh/day.' },
      { slug: 'offtake_industrial',       family: 'LSTM sequence (PMI + utilisation)',              status: 'missing', notes: 'Train + register; output GWh/day baseload.' },
      { slug: 'offtake_storage_cycling',  family: 'XGBoost + LP solve',                              status: 'missing', notes: 'Output optimal cycling profile vs front-winter spread.' },
      { slug: 'wingman-scenario-prior',   family: 'GaussianNB (regime classifier)',                 status: 'reused',  notes: 'Already in Abenix; can repurpose for offtake-regime priors.' },
    ],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `CURRENT: browser computes the curve in-process from a Math.sin() shape — no Abenix call.
TARGET: slider change → contractiq-api → Abenix.execute("contractiq-forecaster-agent", {surface, temp_shift, demand_shock, churn})
              → agent calls Abenix ml_invocations on the relevant offtake_* model → returns {p10,p50,p90,drivers}
              → browser repaints fan chart + SHAP bars`,
    demo_status: 'awaiting-model',
    demo_caveat: DEMO_CAVEAT_AWAITING,
  },

  '/price-engine': {
    title: 'Dynamic Forward Price Engine',
    one_liner: 'Three-layer hybrid (fundamental + econometric + ML) blended forward curve per hub.',
    what_user_does: 'Pick a hub. Adjust the three layer weights. Apply a stress test. Compare the three layers — when they disagree, the residual z-score flags a mispricing signal that routes to /approvals.',
    components: [
      { name: 'Hub selector',          what: '8 hubs across gas + power (TTF, THE, CEGH, PSV, DE/HU/PL/IT power).',          data_source: 'static config',                              is_live: true },
      { name: 'Three-layer curve',     what: 'Fundamental / Econometric / ML lines + blended line.',                          data_source: 'CURRENTLY synthesized in buildCurve()',       is_live: false },
      { name: 'Layer weight sliders',  what: 'Tune weights for each layer.',                                                 data_source: 'in-browser computation',                     is_live: false },
      { name: 'Stress test buttons',   what: 'Cold-winter, pipeline outage, CO2 surge, mild Mediterranean.',                  data_source: 'static config',                              is_live: true },
      { name: 'Mispricing flags',      what: 'Residuals where |z| > 2σ → routes to Approvals HITL.',                          data_source: 'derived from in-browser curve',              is_live: false },
    ],
    abenix_models: [
      { slug: 'wingman-mispricing-fairvalue', family: 'BayesianRidge (12-feature regressor)', status: 'reused',     notes: 'Already in Abenix from wingman; usable for gas/power fair-value.' },
      { slug: 'wingman-mispricing-anomaly',   family: 'IsolationForest',                       status: 'reused',     notes: 'Scores residual z; usable directly.' },
      { slug: 'price_fairvalue_gas_hubs',     family: 'BayesianRidge (per-hub)',                status: 'missing',    notes: 'Per-hub ContractIQ-specific version; could train on EEX/Nord Pool day-ahead history.' },
      { slug: 'price_fairvalue_power_hubs',   family: 'BayesianRidge (per-hub)',                status: 'missing',    notes: 'Same; per power hub.' },
    ],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `CURRENT: client-side buildCurve() computes synthetic three-layer values.
TARGET: hub change → contractiq-api → Abenix.execute("contractiq-price-engine-agent")
        → fundamental_balance code-asset (TimescaleDB read)
        → wingman-mispricing-fairvalue ML model
        → wingman-mispricing-anomaly anomaly scorer
        → blended curve + z-flagged tenors
        → on |z|>2 the agent calls /api/approvals to raise a HITL gate`,
    demo_status: 'awaiting-model',
    demo_caveat: DEMO_CAVEAT_REUSE,
  },

  '/workbench': {
    title: 'Analyst Workbench',
    one_liner: 'SHAP / LIME explainability + analyst override gated by Approvals.',
    what_user_does: 'Pick a recent forecast or price. Read the SHAP waterfall to understand the AI\'s reasoning. Add an annotation. If you disagree, submit an override with rationale — it routes through Approvals so the head of desk signs off before it overwrites the model.',
    components: [
      { name: 'Recent forecasts list', what: 'Index of recent forecast / price executions.',                                data_source: 'CURRENTLY hardcoded; should read Abenix executions',  is_live: false },
      { name: 'SHAP waterfall',        what: 'Per-feature contribution to the prediction.',                                  data_source: 'static array — needs shap_explainer code-asset',     is_live: false },
      { name: 'Annotations',           what: 'Pin a note to a specific forecast.',                                           data_source: 'in-memory only — needs contractiq_annotations table',is_live: false },
      { name: 'Override flow',         what: 'Override value + reason → fires Abenix /approvals.',                            data_source: 'POST /api/approvals — wires to live Abenix HITL gate',is_live: true },
    ],
    abenix_models: [],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `CURRENT: forecast list is hardcoded JSON; SHAP bars are static.
TARGET: workbench reads /api/contractiq/forecasts (new table backed by contractiq_forecasts) → per-forecast SHAP via Abenix shap_explainer code-asset (NOT YET BUILT).
Override is already live: submit → POST /api/approvals (Abenix) → head-of-desk inbox.`,
    demo_status: 'partial-live',
    demo_caveat: 'Override flow is live (routes to Abenix Approvals). SHAP waterfall + forecast list are layout demo until the shap_explainer code-asset is built + the contractiq_forecasts table is wired.',
  },

  '/model-performance': {
    title: 'Performance & Backtest',
    one_liner: 'Per-model MAE / RMSE / MAPE timeline + drift detection + backtest harness.',
    what_user_does: 'Pick a model from the registry. Read its 30-day MAPE timeline + PSI drift signal. Trigger a 365-day backtest to see how it would have performed historically.',
    components: [
      { name: 'Models table',          what: 'Live read of Abenix ml_models registry — every registered model with metrics.',data_source: 'GET /api/contractiq/ml-models/registry',                         is_live: true },
      { name: 'Accuracy timeline',     what: '30-day rolling MAPE per model.',                                                 data_source: 'CURRENTLY synthesized; needs ml_invocations aggregation', is_live: false },
      { name: 'Drift PSI',             what: 'Population stability index; flips Stable → Watch → Drifting.',                  data_source: 'CURRENTLY synthesized; needs feature-distribution job',   is_live: false },
      { name: '365-day backtest',      what: 'One-click historical replay with strict point-in-time joins.',                   data_source: 'NOT BUILT — button shows synthesized numbers',            is_live: false },
    ],
    abenix_models: [
      { slug: 'contractiq-risk-tier-predictor', family: 'sklearn classifier', status: 'registered' },
      { slug: 'contractiq-counterparty-default', family: 'sklearn regressor', status: 'registered' },
      { slug: 'contractiq-price-anomaly',       family: 'IsolationForest',    status: 'registered' },
      { slug: 'contractiq-clause-classifier',   family: 'sklearn classifier', status: 'registered' },
      { slug: 'wingman-mispricing-fairvalue',   family: 'BayesianRidge',      status: 'reused' },
      { slug: 'wingman-mispricing-anomaly',     family: 'IsolationForest',    status: 'reused' },
    ],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `models table → contractiq-api /api/contractiq/ml-models/registry → Abenix /api/ml-models (real registry)
accuracy timeline + drift + backtest → CURRENTLY synthesized; production requires:
  - aggregating ml_invocations table per (model, hour) for MAPE
  - feature-store PSI job (cron)
  - backtest harness as a separate code-asset`,
    demo_status: 'partial-live',
    demo_caveat: 'The models table reads the real Abenix ml-models registry. Accuracy timelines + drift + backtest are layout-demo; production needs ml_invocations aggregation + a PSI cron job + a backtest harness code-asset.',
  },

  '/recommendations': {
    title: 'Recommendations',
    one_liner: 'LLM-synthesised buy / sell / hedge / hold theses across desks, routed through Approvals.',
    what_user_does: 'Read each recommendation card — desk, action, PV, confidence, drivers. Click into the workbench to see the underlying SHAP. Approve / reject through the standard Approvals gate.',
    components: [
      { name: 'Recommendation cards', what: 'One card per active recommendation across desks.',                                data_source: 'CURRENTLY hardcoded; should read contractiq_recommendations table', is_live: false },
      { name: 'Desk filters',         what: 'Gas / power / LNG / environmental / cross.',                                       data_source: 'client-side filter',                                              is_live: true },
      { name: 'KPI strip',            what: 'Open / awaiting / total PV / avg confidence.',                                    data_source: 'derived from hardcoded cards',                                    is_live: false },
    ],
    abenix_models: [
      { slug: 'recommendation_thesis_llm', family: 'Claude Haiku 4.5 (LLM thesis synthesis)', status: 'missing', notes: 'Needs an agent registered in Abenix that consumes forecast + price + anomaly inputs and emits a thesis JSON.' },
    ],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `CURRENT: hardcoded RECS array in browser.
TARGET: recommendations table populated by a daily contractiq-recommendation-engine agent on Abenix → cards read GET /api/contractiq/recommendations. Approve/reject flows through Abenix /api/approvals (already live).`,
    demo_status: 'awaiting-model',
    demo_caveat: DEMO_CAVEAT_AWAITING,
  },

  '/data-fabric': {
    title: 'Data Fabric & Harmonization',
    one_liner: 'Connector health + ingest lag + data quality across every external source.',
    what_user_does: 'Scan the 22 connector rows. Filter by category. Click a row to see the last 24h ingest pattern + any anomalies. Use this as the operational health page for the data plane.',
    components: [
      { name: 'Connector table',     what: '22 sources (exchanges, TSOs, weather, SCADA, news, macro, asset, client).',       data_source: 'CURRENTLY hardcoded — should read contractiq_market_data_sources + Abenix executions for live lag', is_live: false },
      { name: 'KPI strip',           what: 'Total connectors / healthy / rows-per-hour / avg quality / lakehouse status.',     data_source: 'derived from hardcoded table',                       is_live: false },
      { name: 'Pipeline schematic',  what: 'SVG flowchart: sources → adapter registry → anomaly imputer → lakehouse.',         data_source: 'static SVG render',                                  is_live: true },
      { name: 'Category filter',     what: 'Filter rows by category chip.',                                                   data_source: 'client-side',                                        is_live: true },
    ],
    abenix_models: [],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `CURRENT: 22-connector list is hardcoded.
TARGET: each connector row should read live status from contractiq_market_data_sources (last_synced_at + last_value) + Abenix ml_invocations for ingest counters. Anomaly imputer = a real code-asset that runs on every batch.`,
    demo_status: 'demo-seed-only',
    demo_caveat: 'The connector list is hardcoded for layout demonstration. Production requires (a) registering each source in contractiq_market_data_sources, (b) running a TimescaleDB ingestion pipeline per source, (c) reading lag + quality metrics from the live ingestion jobs.',
  },

  '/commodities/gas': commodityDoc('Natural Gas', 'TTF / THE / CEGH / PSV / NBP', 'gas'),
  '/commodities/power': commodityDoc('Power', 'DE / HU / PL / CZ / IT / FR / Nordic', 'power'),
  '/commodities/lng': commodityDoc('LNG', 'JKM / Krk / Brunsbüttel / Spanish terminals', 'lng'),
  '/commodities/environmental': commodityDoc('Environmental', 'EUA / GoO / biomethane / CBAM', 'environmental'),

  '/contracts': {
    title: 'My Contracts',
    one_liner: 'List of every uploaded contract with extraction status + clause coverage.',
    what_user_does: 'See every contract you\'ve uploaded. Click into one for the full extraction (clauses, parties, dates, events, dependency DAG).',
    components: [
      { name: 'Contracts table', what: 'Every row in contractiq_contracts.', data_source: 'GET /api/contractiq/contracts', is_live: true },
      { name: 'Upload CTA',      what: 'Routes to /upload.',                  data_source: 'static link',                    is_live: true },
    ],
    abenix_models: [
      { slug: 'contractiq-clause-classifier', family: 'sklearn classifier', status: 'registered', notes: 'Tags each extracted clause with one of N clause types.' },
    ],
    abenix_agents: [ABENIX_EXTRACTOR],
    abenix_tools: [],
    data_flow: `upload → contractiq-api → Abenix.execute("contractiq-extractor", {pdf})
agent runs multi-pass extraction → returns {clauses, parties, events, leg_structure}
contractiq-api persists to contractiq_contracts + contractiq_clauses + contractiq_events`,
    demo_status: 'fully-live',
  },

  '/upload': {
    title: 'Upload Contract',
    one_liner: 'Drop a PDF / DOCX / TXT contract. Multi-pass extraction fires automatically.',
    what_user_does: 'Drag-drop a contract (or browse). The page shows live extraction progress. When done you can jump straight into the contract detail.',
    components: [
      { name: 'Dropzone',          what: 'Accepts PDF/DOCX/TXT. Multi-file = serial upload with per-file progress.', data_source: 'POST /api/contractiq/contracts/upload', is_live: true },
      { name: 'Progress feed',     what: 'Live SSE stream of the extraction agent\'s tool calls.',                  data_source: 'GET /api/contractiq/contracts/{id}/stream', is_live: true },
    ],
    abenix_models: [
      { slug: 'contractiq-clause-classifier', family: 'sklearn classifier', status: 'registered' },
    ],
    abenix_agents: [ABENIX_EXTRACTOR, { slug: 'contractiq-deep-extractor', role: 'long-tail field rescue pass', status: 'seeded' }],
    abenix_tools: [],
    data_flow: `drag-drop → contractiq-api → Abenix.execute("contractiq-extractor", {file_uri})
extractor runs multi-pass + self-discovering schema → spawns contractiq-deep-extractor for long-tail rescue if completeness < threshold
clauses + events + parties persisted to contractiq Postgres`,
    demo_status: 'fully-live',
  },

  '/help': {
    title: 'Help / Agent Atlas',
    one_liner: 'Every agent + tool + model + module documented in plain English with HTML diagrams.',
    what_user_does: 'Onboard with the "Commodities 101" primer (10-min, beginner). Drill into the "5-module suite" section for the architecture. Click into agent cards for execution details.',
    components: [
      { name: 'Commodities 101',           what: '10-min beginner primer with HTML/SVG diagrams + 35-term glossary.', data_source: 'static markup',                                          is_live: true },
      { name: 'Counterparty data section', what: 'Full architecture of the agentic refresh + 8 tools + coverage matrix.',data_source: 'static markup',                                       is_live: true },
      { name: '5-module suite',            what: 'Data Fabric + Forecaster + Price Engine + Performance + Workbench.',data_source: 'static markup',                                          is_live: true },
      { name: 'Agent catalogue',           what: 'Per-agent card with slug, model, tools, workflow.',                  data_source: 'static specs in page-source',                            is_live: true },
    ],
    abenix_models: [],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `static documentation only — no Abenix calls.`,
    demo_status: 'fully-live',
  },
};

function commodityDoc(label: string, hubs: string, slug: string): PageDoc {
  return {
    title: `${label} hub`,
    one_liner: `Per-${label.toLowerCase()} view into the cross-commodity engines (forecaster + price engine + workbench), filtered to ${label.toLowerCase()} hubs.`,
    what_user_does: `Land here as the trader for ${label.toLowerCase()}. Scan spot prices across the hubs, read the forward curve, see live signals + contracts.`,
    components: [
      { name: 'Spot strip',          what: `4 hub spots (${hubs}).`,                                 data_source: 'CURRENTLY hardcoded — should read contractiq_market_data_points',         is_live: false },
      { name: 'Forward curve',       what: '6-tenor curve chart.',                                  data_source: 'CURRENTLY hardcoded — should read /price-engine output filtered to hub',   is_live: false },
      { name: 'Live signals',        what: 'Mispricing flags + ops alerts for this commodity.',     data_source: 'CURRENTLY hardcoded — should aggregate from contractiq_compliance_alerts', is_live: false },
      { name: 'Active contracts',    what: 'Contracts in this commodity.',                          data_source: 'CURRENTLY hardcoded — should query contractiq_contracts WHERE asset_class', is_live: false },
      { name: 'Glossary',            what: 'Beginner-friendly terms for this commodity.',           data_source: 'static',                                                                   is_live: true },
    ],
    abenix_models: [],
    abenix_agents: [],
    abenix_tools: [],
    data_flow: `CURRENT: every section reads from hardcoded JSON in the component.
TARGET: filter contractiq_market_data_points by hub + read /price-engine forecast + filter contractiq_contracts by asset_class='${slug}'.`,
    demo_status: 'demo-seed-only',
    demo_caveat: 'This page is currently a layout demo using static hub data. Production wiring requires the market_data_sources pipeline to be live (see /data-fabric).',
  };
}

export function getPageDoc(pathname: string): PageDoc | undefined {
  if (PAGE_DOCS[pathname]) return PAGE_DOCS[pathname];
  if (/^\/credit-risk\/counterparty\/[^/]+$/.test(pathname)) return PAGE_DOCS['/credit-risk/counterparty/[id]'];
  return undefined;
}
