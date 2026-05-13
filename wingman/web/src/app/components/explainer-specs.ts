import type { ExplainerSpec } from './ExplainerPanel';

export const WORKBENCH_EXPLAINER: ExplainerSpec = {
  pageKey: 'workbench',
  what:
    'The Arbitrage Workbench scores every active LPG propane corridor on demand. ' +
    'For each route it pulls live spot prices, freight rates, weather, and news, ' +
    'computes a net-arb $/MT, and surfaces a high/medium/low conviction call with ' +
    'a sourced narrative the trader can act on.',
  how:
    'A single OOB agent (wingman-arb-analyzer, Haiku 4.5) is fired per corridor click. ' +
    'It calls six real tools in parallel, runs the financial calculator on the result, ' +
    'and emits a structured JSON envelope the page renders. Live tool-call events are ' +
    'streamed through the SDK to the DAG drawer on the right.',
  tools: [
    'current_time', 'eia_open_data', 'yahoo_finance', 'bunker_fuel',
    'open_meteo', 'tavily_search', 'financial_calculator',
  ],
  models: [
    { name: 'Haiku 4.5', role: 'agent LLM — assembles arb math + narrative' },
  ],
  inputs: [
    'A corridor pair (origin port + destination port)',
    'Live market data pulled by tools at click time (no caching)',
  ],
  outputs: [
    'Net-arb spread in $/MT with cost components broken out',
    'High / medium / low conviction call with a written narrative',
    'Forward curve, vessel scatter, top news drivers',
  ],
};

export const MISPRICING_EXPLAINER: ExplainerSpec = {
  pageKey: 'mispricing',
  what:
    'The Mispricing Lens scores each corridor against a Bayesian fair-value model and ' +
    'an Isolation Forest regime-break detector. The residual z-score (sigma) tells ' +
    'a trader whether today’s observed spread is aligned, stretched, or ' +
    'dislocated relative to fundamentals + the options market.',
  how:
    'For every scan: pull 9 base market features (spots, freight, inventory, exports, FX, ' +
    'weather, season), pull 4 forward-looking options features (Brent IV, Brent 25-delta ' +
    'risk reversal, HH natgas IV, crude put/call OI ratio), call the BayesianRidge ' +
    'fair-value model (returns mean + std), call the Isolation Forest (returns inlier/anomaly), ' +
    'compute residual_sigma = (observed - fair) / std, classify the verdict, draft a thesis ' +
    'with cited news, and route the trade card through the /approvals HITL gate.',
  tools: [
    'current_time', 'eia_open_data', 'yahoo_finance', 'bunker_fuel',
    'open_meteo', 'options_data', 'freight_baltic_blpg', 'freight_worldscale',
    'vessel_specs', 'tavily_search', 'ml_model', 'financial_calculator',
  ],
  models: [
    {
      name: 'wingman-mispricing-fairvalue',
      role: 'BayesianRidge regression on 15 features (8 base + 4 options + 3 freight-quality). Returns posterior mean + std.',
    },
    {
      name: 'wingman-mispricing-anomaly',
      role: 'IsolationForest over 9 features. Flags regime breaks the regression can’t absorb.',
    },
    {
      name: 'Haiku 4.5',
      role: 'agent LLM — drafts the 2–3 sentence thesis citing real Tavily headlines.',
    },
  ],
  inputs: [
    'Corridor id (e.g. USGC-NWE)',
    '12-feature market + options vector built at scan time',
    'Live Tavily news for supply / demand / geo',
  ],
  outputs: [
    'Verdict (aligned / stretched / dislocated / tail) and direction (rich / cheap)',
    'Fair value with P10–P90 credible band',
    'Market regime badge: calm / nervous / skewed-up / skewed-down',
    'Trade card behind /approvals (gate_kind="trade.execute")',
  ],
  extras: [
    {
      title: 'Why options data?',
      body:
        'Listed options prices reveal what futures markets do not: the implied ' +
        'distribution of future outcomes. ATM implied vol shows how nervous the ' +
        'market is. The 25-delta risk reversal (call IV minus put IV) shows skew ' +
        '— positive means supply fear, negative means demand fear. Put/call ' +
        'open-interest ratio shows positioning. Adding these four features to the ' +
        'Bayesian Ridge regression lifts holdout R² by ~4 percentage points ' +
        'versus the 8-feature baseline on the same data.',
    },
    {
      title: 'Sigma to position policy',
      body: [
        '|sigma| < 1: aligned (noise) — no trade.',
        '1 ≤ |sigma| < 2: stretched — half size (up to 12.5 kt).',
        '2 ≤ |sigma| < 3: dislocated — full size, capped at 25 kt.',
        '|sigma| ≥ 3: tail event — size cap lifted, desk-head signoff required.',
        'Isolation Forest anomaly flag is a veto: escalate to a human regardless of sigma.',
      ],
    },
  ],
};

export const SCENARIOS_EXPLAINER: ExplainerSpec = {
  pageKey: 'scenarios',
  what:
    'Forward Scenarios produces probability-weighted 12-month forward curves for a ' +
    'corridor. It mixes a deployed Bayesian (GaussianNB) prior over five regimes ' +
    'with an LLM posterior refined by current news.',
  how:
    'Pull 8 normalised market signals, ask the GaussianNB prior for class probabilities, ' +
    'run four Tavily news searches (supply / demand / geo / regulatory), ask the LLM ' +
    'to refine the probabilities into a posterior, return five named scenarios with ' +
    'their own forward curves and a probability-weighted expected line with P10/P90 band.',
  tools: [
    'current_time', 'eia_open_data', 'yahoo_finance', 'ml_model',
    'tavily_search', 'financial_calculator',
  ],
  models: [
    {
      name: 'wingman-scenario-prior',
      role: 'GaussianNB classifier — prior probabilities over five regimes. 90.8% holdout.',
    },
    {
      name: 'Haiku 4.5',
      role: 'agent LLM — refines prior to posterior using cited news, drafts $/MT impacts.',
    },
  ],
  inputs: [
    'Corridor id', 'Tenor in months (default 12)',
  ],
  outputs: [
    'Five named scenarios with forward curves and posterior probabilities',
    'Probability-weighted expected curve with P10/P90 band',
    'Per-driver $/MT attribution tied to Tavily-sourced headlines',
  ],
};

export const INBOX_EXPLAINER: ExplainerSpec = {
  pageKey: 'inbox',
  what:
    'The Broker Inbox ingests live broker emails (RFQs, indications, post-trade ' +
    'confirmations) and turns each into a structured trade offer that can be ' +
    'queued against existing positions.',
  how:
    'A two-step agent pipeline: wingman-broker-classifier first tags the email ' +
    '(RFQ / IOI / done-deal / chatter), then wingman-broker-parser extracts the ' +
    'structured fields (counterparty, product, size, price, delivery window).',
  tools: ['ml_model', 'text_analyzer', 'date_calculator'],
  models: [
    { name: 'wingman-broker-classifier', role: 'sklearn TF-IDF text classifier' },
    { name: 'Haiku 4.5', role: 'agent LLM — structured-offer extractor' },
  ],
  inputs: ['Raw broker email text'],
  outputs: ['Email intent (RFQ / IOI / done-deal / chatter)', 'Structured offer JSON'],
};

export const OPS_EXPLAINER: ExplainerSpec = {
  pageKey: 'ops',
  what:
    'Operations Watch shows the live position of every LPG / tanker vessel in the ' +
    'top corridors via the public AIS feed, plus a side panel of the top named ' +
    'vessels currently in motion.',
  how:
    'The wingman-ops-monitor agent opens a 5–8 second AIS websocket via the ' +
    'ais_stream tool with bounding boxes per corridor, dedupes by MMSI, and emits a ' +
    'snapshot the page renders as a scatter on a Mercator projection.',
  tools: ['current_time', 'ais_stream'],
  models: [{ name: 'Haiku 4.5', role: 'agent LLM — lightweight orchestration' }],
  inputs: ['Bounding boxes (set per corridor)', 'Ship type filter (84 = LPG tanker)'],
  outputs: ['Vessel scatter with clickable points', 'Top named vessels in motion'],
};

export const STRATEGY_EXPLAINER: ExplainerSpec = {
  pageKey: 'strategy',
  what:
    'Strategy Lab lets a trader express a desk strategy in natural language, ' +
    'encodes it into a structured rule, backtests it on the last 90 days of ' +
    'mock corridor scans, and reports hit-rate plus a P&L curve.',
  how:
    'wingman-strategy-encoder converts the prose to a structured spec, ' +
    'wingman-backtester replays the strategy against the corridor-scan history, ' +
    'wingman-var-simulator runs a Monte Carlo on tail risk. All three are deployed ' +
    'OOB agents on Haiku 4.5.',
  tools: ['ml_model', 'financial_calculator', 'risk_analyzer'],
  models: [
    { name: 'wingman-strategy-encoder', role: 'agent — prose to structured rule' },
    { name: 'wingman-backtester', role: 'agent — historical replay' },
    { name: 'wingman-var-simulator', role: 'agent — Monte Carlo VaR' },
  ],
  inputs: ['Plain-language strategy description'],
  outputs: ['Structured rule JSON', 'Hit-rate', '90-day P&L curve', 'Tail VaR'],
};

export const GRAPH_EXPLAINER: ExplainerSpec = {
  pageKey: 'graph',
  what:
    'The Knowledge Graph (Atlas) exposes Wingman’s typed ontology — ' +
    'corridors, vessels, counterparties, offers, news events — and lets a ' +
    'trader ask natural-language questions that traverse it.',
  how:
    'wingman-graph-query interprets the question, calls the Atlas knowledge_search ' +
    'tool to traverse the graph, and returns a structured subgraph plus a written ' +
    'narrative answer.',
  tools: ['knowledge_search'],
  models: [
    { name: 'Haiku 4.5', role: 'agent LLM — graph traversal + answer synthesis' },
  ],
  inputs: ['Natural-language question'],
  outputs: ['Subgraph (nodes + edges) and narrative answer'],
};

export const APPROVALS_EXPLAINER: ExplainerSpec = {
  pageKey: 'approvals',
  what:
    'The Approvals page is the single human-in-the-loop gate the entire Wingman ' +
    'platform routes through. Broker acknowledgements, strategy activations, and ' +
    'mispricing trade cards all land here, where the desk reviews and signs off.',
  how:
    'Every gate goes through the SDK: forge.approvals.create(...) on the agent ' +
    'side, forge.approvals.signoff()/.deny() on the human side. The Wingman API ' +
    'holds zero local decision state — the platform RBAC is the source of truth.',
  tools: ['approval_gate (via SDK)'],
  inputs: ['Pending gates emitted by agents'],
  outputs: ['Approve / deny with reason — the gate row leaves pending status'],
  extras: [
    {
      title: 'Gate kinds in use',
      body: [
        'trade.execute — mispricing trade cards. Required signoff: 1 desk lead.',
        'broker.ack — broker-offer acknowledgements. Required signoff: 1 trader.',
        'strategy.activate — backtested strategies before they go live. Required signoff: 1 lead.',
      ],
    },
  ],
};

export const EXPLAINERS_BY_KEY: Record<string, ExplainerSpec> = {
  workbench: WORKBENCH_EXPLAINER,
  mispricing: MISPRICING_EXPLAINER,
  scenarios: SCENARIOS_EXPLAINER,
  inbox: INBOX_EXPLAINER,
  ops: OPS_EXPLAINER,
  strategy: STRATEGY_EXPLAINER,
  graph: GRAPH_EXPLAINER,
  approvals: APPROVALS_EXPLAINER,
};
