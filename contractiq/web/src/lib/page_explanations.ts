// Content store for the PageExplainer component. Each page in ContractIQ
// can register a plain-English explanation here, keyed by a stable route
// key (NOT the URL path — URLs may change). A page that has no entry here
// simply renders no explainer card, so partial coverage is safe.
//
// Tone rules for anyone editing this file:
//   - Plain English. Assume the reader is a contracts lawyer or CFO who
//     has never traded an instrument. Define every technical term inline
//     or via the page's glossary.
//   - Be honest about synthetic data. If a number came from a Monte Carlo
//     simulation, say so. If it came from a real public source (Yahoo,
//     EIA, tavily search), say so with citation. If the agent honestly
//     degraded and returned no data, say so.
//   - No marketing words. No "delivers", "leverages", "unlocks", "powerful".
//   - No semicolons in prose.

export type DataQuality = 'real-fetched' | 'agent-simulated' | 'mixed' | 'degraded';

export type SectionExplanation = {
  title: string;
  what_it_shows: string;
  agent_slug?: string;
  tools_used?: string[];
  data_quality: DataQuality;
  layman_note?: string;
};

export type GlossaryEntry = {
  term: string;
  definition: string;
};

export type DataFlowStep = {
  step: number;
  label: string;
  detail: string;
};

export type PageExplanation = {
  routeKey: string;
  page_title: string;
  purpose: string;
  sections: SectionExplanation[];
  data_flow: DataFlowStep[];
  glossary: GlossaryEntry[];
};

// ---------------------------------------------------------------------------
// Shared glossary — define common terms once and spread them into each
// page that uses them. Keep definitions short (1-3 sentences) and free of
// jargon. If a term needs more nuance, put it in the page-specific glossary.
// ---------------------------------------------------------------------------
export const GLOSSARY: Record<string, GlossaryEntry> = {
  forward_curve: {
    term: 'Forward curve',
    definition:
      'A line that shows the agreed price today to buy or sell a commodity at fixed dates in the future. The shape tells you whether the market expects prices to rise (contango) or fall (backwardation).',
  },
  spot_price: {
    term: 'Spot price',
    definition:
      'The price to buy or sell the commodity right now for immediate delivery. Compare against the forward curve to see how the market values waiting.',
  },
  var: {
    term: 'VaR (Value at Risk)',
    definition:
      'A statistical estimate of the worst loss you would expect on a normal bad day, at a chosen confidence level. A 95% one-day VaR of $1M means you would not lose more than $1M on 95 out of 100 trading days.',
  },
  cvar: {
    term: 'CVaR (Conditional Value at Risk)',
    definition:
      'The average loss on the bad days that exceed VaR. Where VaR tells you the threshold, CVaR tells you how bad it gets once you cross it. Also called Expected Shortfall.',
  },
  monte_carlo: {
    term: 'Monte Carlo simulation',
    definition:
      'A method that runs thousands of random possible future paths for a price or risk, then summarises the distribution. Used when there is no closed-form answer because too many variables interact.',
  },
  shap: {
    term: 'SHAP value',
    definition:
      'A number that explains how much each input pushed a model prediction up or down. If your forecast is $52 and "weather" has a SHAP of +$3, weather pushed the prediction $3 higher than the baseline.',
  },
  eua: {
    term: 'EUA',
    definition:
      'European Union Allowance. One EUA is a permit to emit one tonne of CO2 inside the EU emissions trading scheme. Industrial emitters buy them, and the price is set by the ETS market.',
  },
  ttf: {
    term: 'TTF',
    definition:
      'Title Transfer Facility. The Dutch wholesale natural gas hub and the European gas price benchmark. Prices are quoted in EUR per megawatt-hour.',
  },
  jkm: {
    term: 'JKM',
    definition:
      'Japan-Korea Marker. The North Asia spot LNG benchmark published by S&P Global Platts. Prices are quoted in USD per million British thermal units.',
  },
  mtm: {
    term: 'MtM (Mark to Market)',
    definition:
      "Today's value of a contract if you closed it at current market prices. Positive MtM means you are sitting on a paper gain, negative means a paper loss.",
  },
  capacity_factor: {
    term: 'Capacity factor',
    definition:
      'How much energy a power plant actually produced over a period, as a fraction of what it could produce if it ran at full output the whole time. A wind farm with a 35% capacity factor produced 35% of its theoretical maximum.',
  },
  kyc: {
    term: 'KYC (Know Your Customer)',
    definition:
      'The process of verifying who you are doing business with: legal entity, ownership, sanctions exposure, politically exposed persons, adverse media. Required by regulators before onboarding a counterparty.',
  },
  counterparty: {
    term: 'Counterparty',
    definition:
      'The other party in a contract or trade. Counterparty risk is the chance that they fail to deliver or pay what they owe.',
  },
  pd: {
    term: 'PD (Probability of Default)',
    definition:
      'The chance, over a chosen horizon, that a counterparty fails to meet their financial obligations. Usually expressed as a percentage and sourced from credit ratings or a structural model.',
  },
  lgd: {
    term: 'LGD (Loss Given Default)',
    definition:
      'The fraction of exposure you would lose if the counterparty defaults, after collateral and recoveries. An LGD of 40% means you recover 60 cents on the dollar.',
  },
  basis_risk: {
    term: 'Basis risk',
    definition:
      'The risk that the price of what you are hedging and the price of your hedge move apart. Hedging Henry Hub gas with TTF futures works most of the time, until the two diverge.',
  },
  pipeline: {
    term: 'Pipeline (Abenix)',
    definition:
      'A configured sequence of Abenix agents that run in order, passing outputs from one step to the next. Defined by a slug and a YAML config inside agentforge/.',
  },
  agent: {
    term: 'Agent (Abenix)',
    definition:
      'An LLM-driven worker with a defined role, a tool registry, and a runtime sandbox. Pages call agents through the AgentForge SDK rather than embedding business logic in the UI.',
  },
  guardrail: {
    term: 'Runtime guardrail',
    definition:
      'A deterministic post-processing step that the platform applies to an agent output before it reaches the UI. Catches hallucinated numbers, enforces unit consistency, and substitutes the real fetched value when the agent claims it could not get one.',
  },
  correlation_matrix: {
    term: 'Correlation matrix',
    definition:
      'A grid where each cell is a number between -1 and +1 showing how two assets moved together over a window. +1 means they moved in lockstep, 0 means no relationship, -1 means perfect opposite. Used to estimate whether your positions diversify each other or pile on the same bet.',
  },
  marginal_var: {
    term: 'Marginal VaR',
    definition:
      'The amount of VaR a single new position adds to the portfolio. Computed as portfolio VaR with the position minus portfolio VaR without it. Useful for deciding whether a proposed trade increases or reduces overall risk.',
  },
  exposure_base: {
    term: 'Exposure base',
    definition:
      'The dollar notional you are running risk against. A 1% VaR on a $10M exposure is $100k. Always check what base the percentage is applied to before quoting a number.',
  },
  parametric_var: {
    term: 'Parametric VaR',
    definition:
      'A VaR estimate that assumes returns follow a normal distribution and uses the standard deviation directly. Fast, but understates risk in real markets because actual returns have fatter tails than a normal curve.',
  },
  historical_var: {
    term: 'Historical VaR',
    definition:
      'A VaR estimate built by taking the worst losses from the actual return history of the window. Makes no distributional assumption. Limited by what is in the window — if the window does not include a crash, the VaR will not anticipate one.',
  },
  monte_carlo_var: {
    term: 'Monte Carlo VaR',
    definition:
      'A VaR estimate built by simulating thousands of possible return paths from a calibrated model, then reading the loss percentile off the simulated distribution.',
  },
  stress_scenario: {
    term: 'Stress test scenario',
    definition:
      'A defined shock to one or more inputs (price down 30%, FX up 15%, both at once) that is applied to your positions to see what would happen. The output is hypothetical — nothing trades, no money moves. It is a what-if calculation.',
  },
  anomaly_score: {
    term: 'Anomaly score',
    definition:
      'A relative ranking of how unusual a clause looks compared to the rest of your portfolio. Higher means more unusual. Produced by an LLM acting as a judge, so the score is an opinion grounded in language patterns, not a measurement of truth.',
  },
  benchmark_percentile: {
    term: 'Benchmark percentile',
    definition:
      'Where a clause term sits in the distribution of comparable clauses. A liability cap at the 90th percentile means 90% of comparable clauses in the corpus have a lower cap. The corpus is fixed at seed time.',
  },
  clause_taxonomy: {
    term: 'Clause taxonomy',
    definition:
      'The fixed list of clause categories the platform recognises (payment, termination, indemnity, liability, force majeure, change of law, and so on). Every extracted clause is mapped to one of these buckets.',
  },
  llm_as_judge: {
    term: 'LLM-as-judge',
    definition:
      'A pattern where an LLM reads two pieces of text (your clause and a reference) and outputs a score or verdict. The score is the model\'s opinion, not a measurement. Two runs with the same input can return slightly different scores.',
  },
  ppa: {
    term: 'PPA (Power Purchase Agreement)',
    definition:
      'A long-term contract under which a buyer agrees to purchase power from a generator at a defined price or formula. Tenors of 10 to 25 years are common. Can be physical (the buyer takes real megawatt-hours) or virtual (a financial settlement only).',
  },
  hub_vs_node: {
    term: 'Hub vs node pricing',
    definition:
      'Hub price is the average wholesale price for a region (for example PJM West Hub). Node price is the price at the specific point on the grid where a plant injects power. The two can diverge during congestion, and the gap (basis) becomes a real cost for the contract holder.',
  },
  nav: {
    term: 'NAV (Net Asset Value)',
    definition:
      'The total value of what you own minus what you owe, on a single date. For a contract portfolio, NAV is the sum of mark-to-market values across every live contract, net of payables.',
  },
  portfolio_risk_score: {
    term: 'Portfolio risk score',
    definition:
      'A composite number from 0 to 100 produced by the clause classifier model, weighted by contract value. Higher means more risky language is sitting in your book. It is a model output and not a regulatory rating.',
  },
  agent_atlas: {
    term: 'Agent atlas',
    definition:
      'The catalogue of every agent and pipeline available on the platform. Each entry shows the model, the tool registry, the typical cost per call, and a link to the agent definition file.',
  },
  model_card: {
    term: 'Model card',
    definition:
      'A short factsheet for an agent. Names the underlying LLM, the tools the agent can call, the kind of work it does, and known limits. Lives on the agent atlas page.',
  },
  llm_cost: {
    term: 'LLM cost (input/output tokens)',
    definition:
      'LLMs are billed by token, where a token is roughly three quarters of an English word. Input tokens are what the agent reads (prompt plus tool results), output tokens are what it writes. Output tokens are usually three to five times more expensive than input tokens.',
  },
  agentic_workflow: {
    term: 'Agentic workflow',
    definition:
      'A sequence where an LLM decides which tool to call next based on what it has learned so far, rather than following a fixed script. The flexibility is what lets it handle messy real contracts. The trade-off is that it can take longer and cost more than a deterministic script.',
  },
  deterministic_post_processor: {
    term: 'Deterministic post-processor',
    definition:
      'A plain function (no LLM) that runs after the agent finishes. It validates numbers, swaps in real fetched values when the agent claimed none, drops invented citations, and clamps outputs into the legal range. Same input always gives the same output.',
  },
  met_template: {
    term: 'MET template',
    definition:
      'A standardised KYC report layout. Captures a tri-indicator score, an intermediate compliance checklist, an outcome, and the sign-off chain. Every KYC on this page is produced in that shape so the same form reads cleanly to a local KYC expert, a compliance officer, or group compliance.',
  },
  tri_indicator: {
    term: 'Tri-indicator score',
    definition:
      'A 15-75 number built from three sub-scores: Country (CPI rank), Notional (size of annual contracted volume), Industry (segment risk). Each sub-score is 5-25. The aggregated number selects the check tier (Simplified, Standard, Enhanced, Special).',
  },
  cpi_rank: {
    term: 'CPI rank (Corruption Perceptions Index)',
    definition:
      'A country ranking published yearly by Transparency International. Scores run 0 (highly corrupt) to 100 (very clean). A low CPI score raises country risk in the KYC tri-indicator score.',
  },
  transparency_international: {
    term: 'Transparency International',
    definition:
      'The Berlin-based non-government organisation that publishes the Corruption Perceptions Index. Their public JSON snapshot is the source for the Country (CPI) sub-score in every KYC run on this page.',
  },
  nace: {
    term: 'NACE industry code',
    definition:
      'The standard EU classification of economic activities. Each KYC industry option maps to a NACE family, which drives the Industry sub-score.',
  },
  fatf: {
    term: 'FATF (Financial Action Task Force)',
    definition:
      'The inter-governmental body that publishes grey- and black-lists of countries with weak anti-money-laundering regimes. A FATF flag on the counterparty country forces the KYC tier up to Special.',
  },
  wolfsberg: {
    term: 'Wolfsberg principles',
    definition:
      'A set of private-banking anti-money-laundering standards authored by 13 global banks. The intermediate checklist in the KYC template maps each item to a Wolfsberg control area so the report is defensible against a regulator audit.',
  },
  sanctions_screening: {
    term: 'Sanctions screening',
    definition:
      'Looking up an entity (and its directors, owners and ultimate beneficial owners) against OFAC, EU, UN and UK sanctions lists. A hit on any list is a hard stop for onboarding.',
  },
  pep: {
    term: 'PEP (Politically Exposed Person)',
    definition:
      'Someone holding a prominent public position, their close family, or close associates. PEP status does not block a relationship, but it forces enhanced due diligence.',
  },
  ubo: {
    term: 'UBO (Ultimate Beneficial Owner)',
    definition:
      'The natural person who ultimately owns or controls a legal entity, typically defined as more than 25% ownership or equivalent control. Identifying the UBO is a regulatory requirement for KYC.',
  },
  risk_tier: {
    term: 'Counterparty risk tier',
    definition:
      'A traffic-light label (green, amber, red) attached to each counterparty in the seed table. Driven by credit score and observed limit utilisation. Drives the colour of the heat-map tile.',
  },
  credit_utilisation: {
    term: 'Credit utilisation',
    definition:
      'How much of the credit limit you have granted a counterparty is currently being used by live trades. Shown as a percentage. High utilisation against a low credit score is the classic concentration risk.',
  },
  settle_limit: {
    term: 'Settle limit',
    definition:
      'The maximum unpaid settlement exposure you will carry with a counterparty at any moment. Distinct from credit limit, which sizes notional. Settle limits protect against payment failure on the day of delivery.',
  },
  isda: {
    term: 'ISDA master agreement',
    definition:
      'The standard bilateral derivatives contract published by the International Swaps and Derivatives Association. The KYC checklist confirms whether one is in place because it changes how exposure netting and default close-out work.',
  },
  moodys_orbis: {
    term: "Moody's Orbis",
    definition:
      "Bureau van Dijk's global private-company database, owned by Moody's. The KYC agent will call it when configured. In this deployment the credential is not provisioned, so the tool returns an explicit \"unavailable\" banner rather than a fabricated answer.",
  },
  fair_value: {
    term: 'Fair value',
    definition:
      'A model-implied price that says what the commodity should cost given the inputs (storage, weather, OPEC quotas, EUA price, etc.). The gap between fair value and the current market quote is the tradeable signal. Higher than market means market looks cheap, lower means market looks rich.',
  },
  spot_anchor: {
    term: 'Spot anchor',
    definition:
      'The single live front-month print the agent fetches from a public feed (Yahoo Finance, EIA series) and uses to ground the forward curve. Every other tenor on the curve is computed relative to this anchor, so if the anchor is wrong the whole curve is wrong.',
  },
  p10_p50_p90: {
    term: 'P10 / P50 / P90',
    definition:
      'Percentiles of a simulated distribution. P50 is the median (half the simulated paths land above, half below). P10 is the 10th percentile (only 1 in 10 paths land below it — a downside tail). P90 is the 90th percentile (only 1 in 10 land above — an upside tail). The band between P10 and P90 is an 80% confidence interval.',
  },
  seasonality: {
    term: 'Seasonality',
    definition:
      'A predictable repeating pattern across the year. Gas prices rise into winter heating demand, power prices spike on summer cooling load, jet fuel cracks widen for summer travel. The forward curve bakes the consensus seasonal shape into its tenor prices.',
  },
  contango: {
    term: 'Contango',
    definition:
      'A forward curve that slopes upward — later delivery costs more than today. Usually signals oversupply now (cheap to buy today) and a market expectation of recovery, or a storage cost being priced into future tenors.',
  },
  backwardation: {
    term: 'Backwardation',
    definition:
      'A forward curve that slopes downward — later delivery costs less than today. Usually signals tight supply now (today is expensive) and an expectation that the squeeze will ease in future months.',
  },
  basis_vs_benchmark: {
    term: 'Basis (vs benchmark)',
    definition:
      'The price difference between a local hub and the benchmark it trades against. THE-TTF basis is what German gas trades at over (or under) the Dutch benchmark. Basis moves with pipeline congestion, storage levels and cross-border flow constraints.',
  },
  brent: {
    term: 'Brent',
    definition:
      'North Sea waterborne crude. The global crude benchmark — about two thirds of physical crude trades are priced against Brent. Quoted in USD per barrel.',
  },
  wti: {
    term: 'WTI',
    definition:
      'West Texas Intermediate. The US inland crude benchmark, delivered to Cushing Oklahoma. Trades at a discount to Brent reflecting US shale supply and inland pipeline constraints. Quoted in USD per barrel.',
  },
  rbob: {
    term: 'RBOB',
    definition:
      'Reformulated Blendstock for Oxygenate Blending. The NYMEX gasoline futures contract that US refiners and retailers hedge against. Quoted in USD per gallon.',
  },
  ulsd: {
    term: 'ULSD',
    definition:
      'Ultra-Low Sulphur Diesel. The NYMEX heating-oil and diesel benchmark, 15 ppm sulphur. Quoted in USD per gallon. Tracks middle-distillate demand from trucking, rail, marine and heating.',
  },
  epex: {
    term: 'EPEX',
    definition:
      'European Power Exchange. The day-ahead and intraday auction operator for Germany, France, Austria, Switzerland and several other Central European zones. The DE day-ahead clear on EPEX is the German power benchmark.',
  },
  nord_pool: {
    term: 'Nord Pool',
    definition:
      'The Nordic and Baltic power exchange. The Nord Pool system price is the unconstrained Nordic day-ahead reference, set by hydro reservoir levels and Continental coupling. Quoted in EUR per megawatt-hour.',
  },
  ercot: {
    term: 'ERCOT',
    definition:
      'Electric Reliability Council of Texas. The Texas ISO operating an isolated grid (almost no interconnections to the rest of the US). ERCOT North Hub is the Dallas-area locational price and one of the most-traded US power points. Quoted in USD per megawatt-hour.',
  },
  pjm: {
    term: 'PJM',
    definition:
      'PJM Interconnection. The grid operator covering 13 US Mid-Atlantic and Midwest states plus DC. PJM Western Hub is the heavily traded West-PA/OH locational price. Quoted in USD per megawatt-hour.',
  },
  newcastle_thermal: {
    term: 'Newcastle thermal',
    definition:
      'Thermal coal loaded FOB at Newcastle, Australia, 6000 kcal/kg energy content. The Pacific-basin thermal coal benchmark — Japanese, Korean and Chinese utilities reference it. Quoted in USD per tonne.',
  },
  api2_api4: {
    term: 'API2 / API4',
    definition:
      'Two thermal coal indices. API2 is delivered into Amsterdam-Rotterdam-Antwerp (the European import benchmark). API4 is loaded FOB Richards Bay South Africa. Both reference 6000 kcal/kg material. The API2-Newcastle spread tracks Atlantic-Pacific basin tightness.',
  },
  ets: {
    term: 'ETS',
    definition:
      'Emissions Trading Scheme. A cap-and-trade market where the regulator issues a fixed number of allowances and emitters must surrender one allowance per tonne of CO2. The EU ETS is the largest and sets the EUA price.',
  },
  msr: {
    term: 'MSR (Market Stability Reserve)',
    definition:
      'The EU mechanism that withdraws EUA allowances from the market when the surplus is too large and releases them when the surplus is too small. The MSR drains supply, which structurally tightens the EUA market and supports the price floor.',
  },
  opec_quota: {
    term: 'OPEC+ quota',
    definition:
      'The voluntary production ceiling each OPEC and OPEC-aligned country agrees to hold at the cartel meetings. Quotas are the primary lever the cartel uses to defend a price band — cuts tighten supply and lift Brent, unwinds add supply and pressure it.',
  },
  crack_spread: {
    term: 'Crack spread',
    definition:
      'A refiner margin: the price of refined products (gasoline, diesel, jet) minus the cost of crude. The 3-2-1 crack is 3 barrels of crude in, 2 barrels gasoline plus 1 barrel distillate out. Wider cracks mean refining is more profitable and incentivise higher utilization.',
  },
  refinery_utilization: {
    term: 'Refinery utilization',
    definition:
      'The fraction of a refinery system running versus its nameplate capacity. US refinery utilization above 92% means the system is stretched and any unplanned outage spikes refined-product cracks. Below 85% means slack and weaker margins.',
  },
};

// Small helper so each page can pick terms from the shared glossary without
// repeating the definitions.
function pick(keys: (keyof typeof GLOSSARY)[]): GlossaryEntry[] {
  return keys.map(k => GLOSSARY[k]);
}

// ---------------------------------------------------------------------------
// Page entries.
// ---------------------------------------------------------------------------
export const PAGE_EXPLANATIONS: Record<string, PageExplanation> = {
  dashboard: {
    routeKey: 'dashboard',
    page_title: 'Portfolio analytics',
    purpose:
      'This is the home view for ContractIQ. It is meant to answer three questions without you opening a single contract: how big is the book, how risky is it, and what needs my attention this week.\n\nThe page has two modes and it switches automatically. When your tenant has no contracts uploaded yet, the dashboard renders a ghosted demo. The KPI tiles, the radar and the upcoming-events panel all show sample numbers from a synthetic portfolio, dimmed and watermarked as a preview. Nothing on that screen is your data — it is there so the layout and the kind of insight you will get are visible before you upload anything.\n\nOnce you upload your first contract through the [upload page](/upload) the dashboard switches to live mode. Contract count, total capacity in megawatts, total portfolio value in USD and the average portfolio risk score are then computed from your contracts table by aggregate SQL. The radar and the upcoming-events list are computed from your extracted clauses and parsed dates. Nothing on that screen comes from a simulation.',
    sections: [
      {
        title: 'Ghosted demo (no contracts uploaded yet)',
        what_it_shows:
          'A dimmed, watermarked preview of the four KPI tiles, the risk radar and the upcoming-events list, built from a sample portfolio that ships with the app. A banner at the top names the mode explicitly.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'agent-simulated',
        layman_note:
          'The numbers in this mode are sample numbers, not your numbers. They exist so you can see the layout before you upload anything. As soon as your first contract is ingested, this preview disappears and the live mode below takes over.',
      },
      {
        title: 'Headline KPIs (live)',
        what_it_shows:
          'Contract count, total capacity in MW, total portfolio value in USD, and the average portfolio risk score. Each tile is a single SQL aggregate against your contracts table.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These are aggregates of contracts you have already uploaded. No prediction, no simulation. If a contract is missing a field (for example a badly OCRed PDF that lost its capacity figure), it is left out of that aggregate rather than guessed.',
      },
      {
        title: 'Risk by category (live)',
        what_it_shows:
          'A radar chart of average clause risk scores across the categories the extractor knows about: payment, termination, indemnity, liability, force majeure, change of law and so on.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'This panel reads scores already written to the clauses table at ingest time by the contractiq-extractor pipeline. No fresh agent run on page load. The radar shows the average per category, value-weighted. A long spike on one axis means most of the risky language sits in that area.',
      },
      {
        title: 'Upcoming events (live)',
        what_it_shows:
          'Contract renewals, price re-openers and expiries that fall in the next 90 days. Pulled from the dates already parsed out of each contract during ingestion.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'If a date never made it into the extracted fields, the contract will not show up here even if it is genuinely expiring. The fix is to re-ingest the contract, not to edit this view.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/analytics/portfolio',
        detail:
          'A single GET request goes to the ContractIQ API with the user token in the Authorization header. No streaming, no agent in the loop.',
      },
      {
        step: 2,
        label: 'API checks whether the tenant has any contracts',
        detail:
          'If the contracts table is empty for the user, the API returns the static sample-portfolio payload with a ghosted flag set. If there is at least one contract, the API runs the real aggregate SQL instead.',
      },
      {
        step: 3,
        label: 'API runs aggregate SQL against the contracts database',
        detail:
          'No agent is involved at this step. The API runs aggregate queries against the contracts and clauses tables and returns JSON.',
      },
      {
        step: 4,
        label: 'UI renders the charts and tiles from the JSON',
        detail:
          'When the ghosted flag is set, the UI lowers opacity and adds a watermark. Otherwise the same components render at full opacity. No further math in the browser.',
      },
    ],
    glossary: pick(['counterparty', 'capacity_factor', 'mtm', 'nav', 'portfolio_risk_score', 'ppa']),
  },

  'commodities-forward': {
    routeKey: 'commodities-forward',
    page_title: 'Forward curves',
    purpose:
      'This page shows the forward curve for the commodity you are looking at: gas, power, LNG or environmental products. A forward curve is a list of prices agreed today for delivery on future dates. Reading the shape tells you whether the market expects prices to rise or fall over the next year.\n\nThe curve is built by an Abenix agent that fetches what it can from real sources, then fills the rest with a calibrated simulation. The provenance banner at the top of the page tells you, every time, which mode the current view is in. If the banner is green, the entire curve was live. If amber, it is a calibrated simulation. If blue, some tenors are live and others are simulated.',
    sections: [
      {
        title: 'Provenance banner',
        what_it_shows:
          'A coloured strip at the top stating where the curve came from: real-fetched, agent-simulated, or mixed. Also names the data source and the last refresh time.',
        agent_slug: 'contractiq_pipeline_gas_fairvalue',
        tools_used: ['yahoo_finance', 'tavily_search'],
        data_quality: 'mixed',
        layman_note:
          'Always read this banner before quoting a number from this page. The same chart can be a real market snapshot one day and a calibrated guess the next.',
      },
      {
        title: 'Forward curve chart',
        what_it_shows:
          'A line from spot through month-ahead, quarter-ahead, season-ahead and calendar tenors. Y axis is price in the native unit (EUR/MWh for TTF, USD/MMBtu for JKM).',
        agent_slug: 'contractiq_pipeline_gas_fairvalue',
        tools_used: ['yahoo_finance', 'monte_carlo_curve', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'If the agent could not reach Yahoo for a tenor, the runtime guardrail tries to substitute the real fetched value before the curve hits your screen. When that happens, the "agent output corrected" pill appears on the provenance banner.',
      },
      {
        title: 'Live signals',
        what_it_shows:
          'Headlines and alerts that may move the curve. Coloured by severity: grey for informational, amber for caution, red for high impact.',
        agent_slug: 'contractiq_pipeline_gas_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'These are real news items pulled by the fairvalue agent\'s web search at the time of the run. The agent does not invent signals. If web search returned nothing, the panel will be empty rather than padded with filler.',
      },
      {
        title: 'Glossary footer',
        what_it_shows:
          'Hub-specific terms (TTF, JKM, Henry Hub, NBP) defined inline so you do not need to leave the page.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note: 'Static content authored by the team. Not generated by an agent.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'The page passes the commodity slug (gas, power, lng, environmental) and an optional asOf date. Token in the Authorization header.',
      },
      {
        step: 2,
        label: 'API forwards to AgentForge via the SDK',
        detail:
          'The API does not compute the curve itself. It calls the contractiq_pipeline_gas_fairvalue pipeline (or the equivalent for power/LNG/environmental) and waits for the result.',
      },
      {
        step: 3,
        label: 'Agent calls its tools',
        detail:
          'The pipeline first asks yahoo_finance for live front-month prints, then monte_carlo_curve to fill missing tenors with a path simulation calibrated to recent realised volatility, then forward_curve_builder to stitch it into a single curve object.',
      },
      {
        step: 4,
        label: 'Runtime guardrail post-processes the output',
        detail:
          'The platform compares the agent claim against the raw fetched data. If the agent claimed "no live data available" but the fetch tool actually returned values, the guardrail substitutes the real values and sets the post-processed flag. The UI then shows the amber correction pill.',
      },
      {
        step: 5,
        label: 'UI renders curve, signals and provenance',
        detail:
          'No further math in the browser. The chart is a direct plot of the curve array returned by the API.',
      },
    ],
    glossary: pick(['forward_curve', 'spot_price', 'ttf', 'jkm', 'basis_risk', 'monte_carlo', 'guardrail']),
  },

  'credit-risk-kyc': {
    routeKey: 'credit-risk-kyc',
    page_title: 'KYC Standard Check (MET template)',
    purpose:
      'This page runs a Know Your Customer check on a counterparty using the MET-style template: a tri-indicator scoring panel, a 10-row intermediate compliance checklist with low/medium/high risk grades, and a four-state outcome (positive, positive with conditions, negative, pending). Everything you see here is a recommendation produced by the agent — the actual sign-off is a human action gated by role.\n\nThe page is built from public sources, not a paid data feed. Coverage is best for entities with a country corruption-perceptions ranking and an industry segment we can classify. For private firms in low-coverage jurisdictions the agent will openly mark the run as degraded rather than guess.\n\nA key honesty rule: the Moody\'s Orbis lookup currently returns an "unavailable" banner because the Orbis API needs an OAuth2 subscription per tenant. The agent leaves the section empty and says so rather than fabricating a financial-strength score.',
    sections: [
      {
        title: 'Counterparty identity card',
        what_it_shows:
          'Legal name, country of incorporation, registered address, industry segment. You fill these in to start the run.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No agent runs at this step. Just data entry. The dedup lookup that fires when you finish typing the name is a local DB query, not an agent.',
      },
      {
        title: 'Tri-indicator scoring panel',
        what_it_shows:
          'Three indicators that drive the final outcome: Country CPI Rank (Transparency International), Annual Notional band, and Industry Segment risk. Each indicator carries a green/amber/red light. The composite is an LLM-judged ranking, not a regulatory determination.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['country_cpi_lookup', 'industry_segment_risk'],
        data_quality: 'mixed',
        layman_note:
          'The three inputs are real-fetched: CPI rank is from Transparency International, industry risk is a stored lookup table with FATF and Wolfsberg citations, notional is what you typed. The composite verdict is the LLM\'s call based on the MET rubric — that part is a model judgement.',
      },
      {
        title: 'Intermediate compliance checklist',
        what_it_shows:
          'A 10-row checklist (sanctions screen, PEP screen, beneficial ownership, source of funds, etc.) each graded L / M / H. Each row has a one-line "outcome of check" explanation.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['tavily_search'],
        data_quality: 'mixed',
        layman_note:
          'The screening uses live web search for sanctions and adverse-media. The L/M/H grade for each row is an LLM judgement against the row\'s rubric. A "Local KYC Expert" reviewer is expected to override any row before sign-off.',
      },
      {
        title: 'Four-state outcome pill',
        what_it_shows:
          'The single recommendation: positive, positive with conditions, negative, or pending. Above it a one-paragraph reasoning narrative cites the specific findings above.',
        agent_slug: 'kyc-standard-check',
        tools_used: [],
        data_quality: 'agent-simulated',
        layman_note:
          'This pill is the agent\'s recommendation only. It is NOT a sign-off. A sign-off is a separate human action and any H-graded row blocks an automatic "positive" outcome at the API level (HTTP 400 from the sign-off endpoint).',
      },
      {
        title: 'Moody\'s Orbis financial strength',
        what_it_shows:
          'An honest "unavailable" banner. Orbis API requires OAuth2 per tenant subscription and is not wired in this build.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['moodys_orbis_lookup'],
        data_quality: 'degraded',
        layman_note:
          'The agent will not fabricate a financial-strength score. If you need this for the sign-off, pull a snapshot from your existing Orbis subscription and paste it into the audit trail manually.',
      },
      {
        title: 'Per-role sign-off lane',
        what_it_shows:
          'Two sign-off slots: Local KYC Expert and Compliance Officer. Each captures the human reviewer\'s decision, time-stamped, with an optional override note. The next_review_due date is set from the outcome.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The agent does not sign off. Ever. The buttons here record human decisions in the DB. The whole MET template is built around the assumption that two humans review the agent\'s recommendation before the counterparty is approved.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User fills the form and clicks Run KYC',
        detail:
          'The browser posts the identity + commercial context + compliance fields to /api/contractiq/insights/kyc/run.',
      },
      {
        step: 2,
        label: 'contractiq-api forwards to AgentForge via the SDK',
        detail:
          'The API does not compute the score itself. It calls kyc-standard-check via the abenix SDK with the user token. After Wave-2 refactor, no business logic runs in the router.',
      },
      {
        step: 3,
        label: 'kyc-standard-check calls its tools',
        detail:
          'country_cpi_lookup hits the Transparency International CSV. industry_segment_risk reads the seeded FATF/Wolfsberg lookup table. moodys_orbis_lookup returns the documented unavailable banner. tavily_search runs sanctions + adverse-media queries.',
      },
      {
        step: 4,
        label: 'Agent returns the MET-shaped JSON',
        detail:
          'The agent emits tri_indicator, intermediate_checks[] with risk_grade per row, four_state_outcome, next_review_due, and provenance.notes about the Orbis gap.',
      },
      {
        step: 5,
        label: 'API writes the run + UI renders the panels',
        detail:
          'The run lands in the kyc_runs table with the agent recommendation. The sign-off endpoints (/kyc/{id}/sign-off) are gated server-side: an H-graded row blocks a "positive" outcome.',
      },
    ],
    glossary: pick(['kyc', 'counterparty', 'pd', 'lgd', 'guardrail']),
  },

  'credit-risk-counterparty': {
    routeKey: 'credit-risk-counterparty',
    page_title: 'Counterparty credit risk',
    purpose:
      'This page estimates the credit risk you are running on a single counterparty across all your contracts with them. It combines a probability of default with a loss given default to produce expected loss in dollar terms.\n\nProbability of default is taken from public credit ratings where available, and from a structural model (Merton-style) where it is not. Loss given default uses a sector default of 60% unless your contracts specify collateral terms that change it. The page is explicit about which path it took.',
    sections: [
      {
        title: 'Probability of default',
        what_it_shows:
          'Annualised PD as stored on the counterparty row in the database. No live agent run.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The PD value is a field on the counterparty record seeded at tenant setup (e.g. from an internal rating or a manually-entered band). There is no live agent fetching ratings or running a structural model in this build. A 2% PD does not mean the counterparty will default — it means that across a large population of similar entities, about 2 in 100 default in a year. Use it for sizing limits, not for predicting an individual default.',
      },
      {
        title: 'Loss given default',
        what_it_shows:
          'The fraction of exposure you expect to lose if the counterparty defaults, after collateral and recoveries. Stored on the counterparty row.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Like PD, LGD is a counterparty-table field, not a model output. It is whatever was loaded at seed time — a sector default or a manually overridden value. There is no live collateral parser or sector-LGD agent in this build. Re-seed the counterparty record if you want a different number.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/counterparties/{id}',
        detail:
          'The page passes the counterparty id. The API joins the contracts table to get exposure and reads PD and LGD from the counterparty row.',
      },
      {
        step: 2,
        label: 'API reads PD and LGD off the counterparty record',
        detail:
          'No agent run. PD and LGD are stored fields seeded at tenant setup. The API returns whatever is on the row, with a source tag noting that it is a seeded value.',
      },
      {
        step: 3,
        label: 'API computes expected loss',
        detail:
          'Multiplication only: PD × LGD × exposure. A simple validation step checks that PD is in [0,1] and LGD is in [0,1] before returning.',
      },
      {
        step: 4,
        label: 'UI renders panels and totals',
        detail: 'No further math in the browser.',
      },
    ],
    glossary: pick(['counterparty', 'pd', 'lgd', 'mtm', 'guardrail']),
  },

  landing: {
    routeKey: 'landing',
    page_title: 'ContractIQ — landing page',
    purpose:
      'This is the public landing page at /. It explains what ContractIQ does in plain English and gives you a sign-in or sign-up form. Nothing on this page runs an agent. No contract is read, no data is fetched on your behalf, no LLM tokens are spent. It is informational.\n\nThe pitch is short. Upload your PPA — a Power Purchase Agreement, the long-term contract under which a buyer agrees to pay a generator for electricity. In 60 seconds, know every risk. ContractIQ reads the contract, pulls out the clauses, scores each one for legal and commercial risk, and shows you the result on a [dashboard](/dashboard) you can navigate in minutes rather than days. The same flow handles gas supply agreements, tolling agreements, virtual PPAs, carbon and REC contracts, energy derivatives, and precious-metals contracts.\n\nWork only starts after you sign in and upload a contract. Until then the page is static marketing copy. The product, the agents and the dashboards are all behind the login.',
    sections: [
      {
        title: 'Hero — what ContractIQ does',
        what_it_shows:
          'A one-line value claim ("Upload your PPA. In 60 seconds, know every risk."), three or four supporting bullets, and a call to action that scrolls to the sign-in panel.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Static copy authored by the team. No agent runs. The 60-second claim is the typical time for a single-contract ingestion on a medium PPA, measured on our reference cluster. Longer contracts and slower OCR can push it past that.',
      },
      {
        title: 'Supported contract types',
        what_it_shows:
          'Cards listing the contract families the platform can ingest: PPAs (solar, wind, hydro, hybrid, storage-coupled), gas supply agreements, tolling, virtual PPAs, carbon and RECs, and energy derivatives. Each card lists the sub-types and the headline fields the extractor pulls out.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'These cards describe what the product is built for, not what is on your account. The actual extraction runs only after you sign in and upload a contract.',
      },
      {
        title: 'Sign in / register',
        what_it_shows:
          'Email and password fields, a toggle between sign-in and registration, and a link to the password reset flow.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Authentication is a plain database lookup against the local users table. No LLM. No third-party identity provider in the default deployment. Tokens are JWTs signed by the ContractIQ API.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser loads /',
        detail:
          'Server-rendered HTML and a small client bundle. No API call is made until you submit the sign-in form.',
      },
      {
        step: 2,
        label: 'You submit the sign-in form',
        detail:
          'POST to /api/contractiq/auth/login. The API verifies the password against the users table and returns a JWT. No agent in the loop.',
      },
      {
        step: 3,
        label: 'Browser stores the token and routes to /dashboard',
        detail:
          'From that point onwards the application is signed in and the rest of the pages become reachable. The landing page itself remains static and still runs no agents.',
      },
    ],
    glossary: [
      ...pick(['ppa', 'capacity_factor', 'hub_vs_node', 'agentic_workflow']),
      {
        term: 'Energy contract (scope)',
        definition:
          'A binding agreement that prices, schedules or delivers an energy product — power, gas, LNG, carbon, renewable certificates or a metals offtake. ContractIQ ingests the PDF or DOCX and turns it into structured clauses and dates so the rest of the product can reason about it.',
      },
      {
        term: 'Risk score (portfolio)',
        definition:
          'A 0-100 number written by the clause classifier when a contract is ingested. Higher means more risky language on average. It is a model output stored at ingest time, not a live re-scoring on every page load.',
      },
    ],
  },

  help: {
    routeKey: 'help',
    page_title: 'Help centre and agent atlas',
    purpose:
      'This page is two things in one. The top half is the help centre — short explanations of every major feature of ContractIQ, written for someone who has just signed in for the first time. The bottom half is the agent atlas — the catalogue of every agent and pipeline the platform can call on your behalf, with a model card for each one.\n\nThe atlas is meant to be honest about what is running underneath. For each agent it lists the LLM the agent calls (for example Claude Sonnet 4.5 or Haiku 4.5), the registry of tools the agent is allowed to use, the kind of work the agent does, and the typical input-token and output-token cost per call so you can sanity-check your bill. Where an agent has a deterministic post-processor or guardrail attached, that is also named.\n\nIf you want the same explanation in-context for whichever page you are looking at, use the "Explain this page" button visible on every dashboard. That button opens the PageExplainer panel and pulls from the same source of truth as this atlas, scoped to the current route.',
    sections: [
      {
        title: 'Help centre sections',
        what_it_shows:
          'Collapsible sections covering authentication, contract upload, the analytics dashboard, the commodities pages, credit and KYC, market risk, and admin. Each section is a short walkthrough with inline icons in place of screenshots.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Static content authored by the team. Search at the top filters across section titles and body text. No agent runs.',
      },
      {
        title: 'Agent atlas — model cards',
        what_it_shows:
          'A card for each agent in the platform. Each card lists the agent slug, the model behind it, the tools it is allowed to call, the kind of task it does, the typical cost per run in input and output tokens, and a link to the YAML definition file under agentforge/.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The atlas reads from the agent registry on the API at /api/abenix/agents. Counts and costs are the latest published values for each agent. They are point-in-time, so a model migration or a tool change can shift the numbers between releases.',
      },
      {
        title: 'PageExplainer entry point',
        what_it_shows:
          'A short note pointing the user at the "Explain this page" button that sits on every dashboard. That button opens an in-context panel sourced from this same file (page_explanations.ts).',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'When you click "Explain this page" anywhere in the product, you get the layman_note, the data_quality flag and the data_flow steps for that specific page. That is the recommended way to understand what is real and what is simulated without leaving your workflow.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser loads /help',
        detail:
          'The page is rendered from local static content plus a single GET to /api/abenix/agents for the atlas section.',
      },
      {
        step: 2,
        label: 'API returns the agent registry',
        detail:
          'A list of agents with slug, model, tools, role, cost averages and YAML path. No agent execution. The registry is built at deploy time from the YAML files under agentforge/.',
      },
      {
        step: 3,
        label: 'UI renders sections and model cards',
        detail:
          'Search filters the sections live in the browser. The atlas cards are sorted by domain (contracts, commodities, credit, risk, metals, observability).',
      },
    ],
    glossary: pick(['agent_atlas', 'model_card', 'llm_cost', 'agent', 'pipeline', 'agentic_workflow', 'deterministic_post_processor']),
  },

  metals: {
    routeKey: 'metals',
    page_title: 'Precious metals hub',
    purpose:
      'This is the entry page for the precious-metals workspace. It covers gold, silver, platinum and palladium contracts — bullion bars, refiner intake (dore), good-delivery offtake, and the responsible-sourcing chain behind them.\n\nThe hub is contract-centric, not market-centric. The agents under this section read your uploaded metals contracts and pull out specifications (purity, bar weight, loco, pricing reference, assay protocol), audit them against LBMA, LPPM, OECD DDG, RJC, Swiss PMCA and ISO standards, score dispute risk, analyse loco premium and delivery terms, audit responsible-sourcing evidence, and watch your refiner counterparties for status changes on the LBMA Good Delivery List.\n\nThere is no fair-value agent yet. This hub does not quote a live gold or silver spot price, does not build a metals forward curve, and does not produce a metals NAV. Those features are not wired. When they ship they will appear as separate sections on this page with their own provenance banners.',
    sections: [
      {
        title: 'Portfolio overview',
        what_it_shows:
          'Counts of contracts that have been through each agent (extraction, compliance, dispute, sourcing, refiner watch), plus material mix, loco mix, average compliance score, average audit readiness, total expected dispute loss in USD, and refiners flagged at risk.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These numbers are aggregates of agent outputs already saved to the database. The page does not re-run any agent. Refresh comes from running the underlying agents on individual contracts.',
      },
      {
        title: 'Metals extraction',
        what_it_shows:
          'Per-contract specifications pulled from contract text: material, fineness, bar weight and tolerance, good-delivery standard, accepted refiners, loco, delivery window, pricing reference and formula, assay method and tolerance, vaulting type, treatment and refining charges, payable percent per metal, impurity penalties, sanctions clauses.',
        agent_slug: 'contractiq-metals-extractor',
        tools_used: ['document_parser'],
        data_quality: 'mixed',
        layman_note:
          'Real values where the contract spells them out. The extractor returns a confidence number per field. When a field is not in the contract, it is left null rather than guessed.',
      },
      {
        title: 'Compliance audit',
        what_it_shows:
          'Overall compliance score against LBMA Good Delivery, RGG, LPPM, OECD DDG, RJC, ISO 9001 and 14001, Swiss PMCA, HMRC VAT 701/14, REACH, Dodd-Frank 1502 and EU 2017/821. Lists block-level issues, clarification requests, per-standard verdicts and superseded references.',
        agent_slug: 'contractiq-metals-compliance-auditor',
        tools_used: ['document_parser', 'knowledge_search'],
        data_quality: 'mixed',
        layman_note:
          'The standards-reference loader pulls the relevant section text from a local snapshot of each standard. The verdict per section is an LLM judgement against that text. Read the citations under each verdict before treating it as a regulatory pass or fail.',
      },
      {
        title: 'Dispute risk scorer',
        what_it_shows:
          'Aggregate dispute score, tier (low, medium, high, critical), expected loss in USD and as a percent of notional, dimensions (assay, weight, brand, late delivery, sanctioned origin), top recommendations and comparable historical disputes.',
        agent_slug: 'contractiq-metals-dispute-scorer',
        tools_used: ['document_parser', 'knowledge_search'],
        data_quality: 'mixed',
        layman_note:
          'The expected-loss figure is a model output, not a contingency reserve number. The comparable disputes come from a knowledge base of public industry cases.',
      },
      {
        title: 'Loco and delivery',
        what_it_shows:
          'Loco location, reference price per ounce, loco premium percent and per-ounce premium, comparison across major locos (Zurich, London, New York, Shanghai), insurance terms, customs and tariff, chain of integrity, repatriation, vault handover, alerts and recommendations.',
        agent_slug: 'contractiq-metals-loco-analyzer',
        tools_used: ['document_parser'],
        data_quality: 'mixed',
        layman_note:
          'Reference prices are read from the contract text — this agent does not yet fetch a live spot. Cross-loco comparison rows reflect typical industry premia at the time the agent was last calibrated.',
      },
      {
        title: 'Responsible sourcing',
        what_it_shows:
          'Origin country and risk class, mine and refiner identity and disclosure, transport route, OECD 5-step and LBMA RGG step evidence, RJC chain of custody, dore integrity protocol applicability, high-risk-origin flag, Russian-origin exclusion flag, gaps and audit-readiness score.',
        agent_slug: 'contractiq-metals-sourcing-tracker',
        tools_used: ['document_parser', 'knowledge_search'],
        data_quality: 'mixed',
        layman_note:
          'The audit-readiness score is a model summary of the gap count and the evidence found. It is meant for triage before an internal audit, not as the audit itself.',
      },
      {
        title: 'Refiner watch',
        what_it_shows:
          'Per-refiner counterparty card: LBMA gold and silver status, LPPM platinum and palladium status, OFAC SDN flag, next audit date, last audit findings, count of your contracts that name this refiner, last alert.',
        agent_slug: 'contractiq-metals-refiner-watch',
        tools_used: ['market_data', 'market_data', 'tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Status fields come from the public LBMA and LPPM Good Delivery List snapshots and the OFAC SDN search. A status change since the last scan triggers an alert that is shown on the card.',
      },
      {
        title: 'Fair-value pricing — not yet wired',
        what_it_shows:
          'Reserved space for a spot price, a forward curve and a portfolio NAV on the four metals.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'degraded',
        layman_note:
          'No metals_fairvalue agent exists today. This hub does not quote a live gold or silver price, does not build a metals forward curve, and does not produce a metals NAV. When those land they will be documented here with their data sources.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser loads /metals',
        detail:
          'A single GET request goes to /api/contractiq/metals with the user token. Returns aggregate counts and averages from each of the six metals tables.',
      },
      {
        step: 2,
        label: 'You drill into a module',
        detail:
          'Clicking a module card opens the per-feature page (extract, compliance, disputes, loco, sourcing, refiners). Each of those pages can run the underlying agent against a chosen contract.',
      },
      {
        step: 3,
        label: 'API forwards to AgentForge via the SDK',
        detail:
          'For run actions, the API calls _call_abenix against the agent slug listed in the section above. Each agent call is retried up to three times if the output does not parse as JSON.',
      },
      {
        step: 4,
        label: 'Agent runs its tools and returns a structured result',
        detail:
          'Tool calls (contract text reader, standards reference loader, comparable disputes KB, LBMA/LPPM/OFAC lookups) are recorded so the guardrail can audit them. The result row is saved into the relevant metals table.',
      },
      {
        step: 5,
        label: 'UI renders the saved result',
        detail:
          'No further computation in the browser. The overview page re-reads its aggregates on next load.',
      },
    ],
    glossary: pick(['ppa', 'nav', 'counterparty', 'agent', 'pipeline', 'guardrail']),
  },

  contracts: {
    routeKey: 'contracts',
    page_title: 'My contracts',
    purpose:
      'This is the list of every contract you have uploaded to ContractIQ. One row per contract, with the basics pulled from the extraction step: counterparty, product, notional, start and end dates, status. Click into a row to see the full clause-level breakdown.\n\nNothing on this page is a model output. The list is a direct read from the contracts table in the local database. If a contract is here, it has finished ingesting. If a contract you uploaded is missing, it is either still running through the [contract ingest pipeline](/upload) or it failed and is on the errors tab.',
    sections: [
      {
        title: 'Contract list',
        what_it_shows:
          'One row per contract you own. Columns are counterparty, product, notional, start date, end date, status and risk score. Sorting and filtering happen client-side on the rows already loaded.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These are your records as stored. The risk score column is a number the clause classifier wrote at ingest time, not a live re-scoring. If you want the latest score, re-run extraction on that contract.',
      },
      {
        title: 'Quick filters',
        what_it_shows:
          'Chips to filter by counterparty, product and status. Selecting a chip narrows the list above without a round trip.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Filtering is local. If you want a contract that is not in the loaded page, change the search box at the top, which does hit the database.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/contracts',
        detail:
          'A single GET with the user token. Pagination and search are query params. No agent is involved.',
      },
      {
        step: 2,
        label: 'API runs SQL against the contracts table',
        detail:
          'A scoped select with row-level filtering by tenant and owner. Returns the rows as JSON.',
      },
      {
        step: 3,
        label: 'UI renders the table',
        detail:
          'No computation in the browser beyond formatting dates and numbers.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'mtm', 'ppa', 'capacity_factor']),
      {
        term: 'Contract status',
        definition:
          'Where the contract is in its life cycle: pending (uploaded, not yet extracted), active (extracted and live), expired (end date in the past), terminated (closed early). The list shows the status as written at ingest — re-extract a contract to refresh it.',
      },
      {
        term: 'Notional',
        definition:
          'The headline size of the contract in money terms. For a fixed-price PPA it is price times expected volume across the tenor. For a tolling deal it is the capacity payment plus the variable component. Used for sorting and exposure aggregation, not for valuation.',
      },
      {
        term: 'Tenor',
        definition:
          'The length of time the contract covers, from start date to end date. A 15-year PPA has a 15-year tenor. Tenor drives how long the position sits on the book and how far out the forward P&L chart goes.',
      },
      {
        term: 'Expiry',
        definition:
          'The end date of the contract as parsed from the document. The dashboard upcoming-events panel uses this field to flag renewals coming up in the next 90 days. A missing or unparsed expiry will keep the contract off that panel.',
      },
    ],
  },

  upload: {
    routeKey: 'upload',
    page_title: 'Upload a contract',
    purpose:
      'This page is the entry point for getting a contract into ContractIQ. You drop a PDF or DOCX file, the file gets stored, and then the contract ingest pipeline runs a chain of agents to turn the document into structured data.\n\nThe ingest takes about 30 to 60 seconds end to end depending on the length of the document. During that window the UI shows live progress as each agent in the pipeline reports in. When the pipeline finishes, the contract shows up on the [My contracts](/contracts) list and the extracted fields become queryable everywhere else in the product.',
    sections: [
      {
        title: 'File drop zone',
        what_it_shows:
          'A target for PDF or DOCX upload. The file is sent to the API which writes it to object storage and creates a contract row in pending status.',
        agent_slug: undefined,
        tools_used: ['document_parser'],
        data_quality: 'real-fetched',
        layman_note:
          'Nothing is extracted yet at this point. All that has happened is the file is saved and a placeholder row exists.',
      },
      {
        title: 'Ingest progress',
        what_it_shows:
          'Live status of each step in the contract ingest pipeline. You see the parser running, then the clause extractor, then the risk analyzer, then valuation, each transitioning from pending to running to done.',
        agent_slug: 'contractiq-pipeline',
        tools_used: ['document_parser', 'document_parser', 'invoke_agent', 'invoke_agent', 'invoke_agent'],
        data_quality: 'mixed',
        layman_note:
          'The contractiq-pipeline orchestrator chains the parser, the contractiq-extractor agent (for headline fields and clauses), and contractiq-market-exposure for initial valuation. If a step fails (bad PDF, unreadable text, missing clause we cannot infer), the pipeline does not silently make up an answer. The step is marked failed and the contract still lands with whatever fields the earlier steps managed to extract.',
      },
      {
        title: 'Extracted preview',
        what_it_shows:
          'Once the pipeline finishes, a short preview of what came out: counterparty name, product, notional, start and end dates, and a count of clauses extracted.',
        agent_slug: 'contractiq-extractor',
        tools_used: ['structured_extractor'],
        data_quality: 'mixed',
        layman_note:
          'The values here are model outputs from the contractiq-extractor agent. Anything you disagree with can be corrected on the contract detail page after the upload finishes.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser POSTs the file to /api/contractiq/contracts/upload',
        detail:
          'Multipart form upload. The API stores the file, creates a row in pending status and returns the contract id.',
      },
      {
        step: 2,
        label: 'API kicks off the contract ingest pipeline',
        detail:
          'A call to AgentForge via the SDK starts the contractiq-pipeline ingest pipeline with the file id and the contract id.',
      },
      {
        step: 3,
        label: 'Parser agent extracts text',
        detail:
          'PDF or DOCX is parsed to raw text. OCR is applied if the file has no embedded text. Bad scans can lose information here, which is why later steps may be missing fields.',
      },
      {
        step: 4,
        label: 'Clause extractor splits the text into structured clauses',
        detail:
          'A schema-driven extraction step pulls each clause into a typed record: payment, termination, force majeure, change of law and so on. Each clause keeps a pointer back to its source text.',
      },
      {
        step: 5,
        label: 'Risk classifier scores each clause',
        detail:
          'The classifier writes a 0-100 risk score per clause and an overall contract risk score. These are the numbers you see on the [contracts list](/contracts) and the dashboard radar.',
      },
      {
        step: 6,
        label: 'Valuation agent computes initial MtM',
        detail:
          'The `contractiq-market-exposure` agent fetches the current spot for the underlying commodity and writes a first mark-to-market estimate, so the contract has a number from the moment it lands.',
      },
      {
        step: 7,
        label: 'UI flips to done and links to the contract',
        detail:
          'Browser polls the contract status. When it goes done, the page offers a link into the contract detail view.',
      },
    ],
    glossary: [
      {
        term: 'Contract ingest pipeline',
        definition:
          'The configured Abenix pipeline that turns an uploaded PDF or DOCX into structured contract data. Runs the parser, clause extractor, risk classifier and valuation agents in order.',
      },
      {
        term: 'Schema-driven extraction',
        definition:
          'Extraction where the LLM is forced to fill a predefined JSON schema. The model cannot return free text. This prevents missing fields and keeps the output usable by downstream code.',
      },
      {
        term: 'Clause extraction',
        definition:
          'The step that splits the contract body into individual clauses (payment, termination, indemnity, force majeure, change of law and so on), each kept with a pointer back to its source text for audit.',
      },
      ...pick(['mtm', 'pipeline', 'agent', 'guardrail']),
    ],
  },

  valuation: {
    routeKey: 'valuation',
    page_title: 'Valuation: MtM and forward P&L',
    purpose:
      'This page values a contract today and projects how that value would change under different forward price paths. The headline number is mark-to-market: the value of closing the position right now at current market prices. The forward P&L chart shows what the contract is worth across the remaining tenor under the live forward curve.\n\nThe MtM is a model output. The `contractiq-market-exposure` agent reads the contract terms (price formula, volume profile, tenor), fetches the current spot and forward curve, and computes the difference against the contract strike. The contract terms are real (parsed from your uploaded document), the market spot is real (fetched from Yahoo or the configured feed), and the MtM is the agent doing the arithmetic. It is an estimate of closing value, not a settlement and not a guaranteed cash number.',
    sections: [
      {
        title: 'Mark-to-market headline',
        what_it_shows:
          'A single dollar number: the value of the contract if you closed it at current prices. Positive means a paper gain, negative means a paper loss.',
        agent_slug: 'contractiq-market-exposure',
        tools_used: ['yahoo_finance', 'monte_carlo_curve', 'financial_calculator'],
        data_quality: 'mixed',
        layman_note:
          'This number is the agent computing strike minus market times remaining volume, summed across tenor. It is not a quote you could lift from a broker, and your counterparty might value the same contract differently.',
      },
      {
        title: 'Contract terms used',
        what_it_shows:
          'The exact fields the valuation read: notional, volume profile, strike or price formula, start and end dates. These come directly from your uploaded contract.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'If a number here looks wrong, the issue is in extraction not in valuation. Fix the field on the contract detail page and re-run valuation.',
      },
      {
        title: 'Forward P&L curve',
        what_it_shows:
          'A line chart showing the projected value of the contract month by month across its remaining tenor, under the current forward curve.',
        agent_slug: 'contractiq-market-exposure',
        tools_used: ['monte_carlo_curve', 'financial_calculator'],
        data_quality: 'mixed',
        layman_note:
          'The forward curve itself is fetched live where possible and simulated where not (same logic as the [forward curves page](/commodities/forward)). The shape of this line is sensitive to that curve. If the curve moves, the line moves with it.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/insights/valuation/run',
        detail:
          'The page passes the contract id and an optional asOf date.',
      },
      {
        step: 2,
        label: 'API loads the contract terms from the database',
        detail:
          'The extracted fields (strike, volume, tenor, price formula) are pulled from the contracts and clauses tables. No model call yet.',
      },
      {
        step: 3,
        label: 'API forwards to AgentForge via the SDK',
        detail:
          'Calls the contractiq-market-exposure agent with the contract terms as input.',
      },
      {
        step: 4,
        label: 'Agent fetches current market data',
        detail:
          'Spot price from yahoo_finance or the configured commodity feed. Forward curve from forward_curve_builder, which reuses the same logic as the [forward curves page](/commodities/forward).',
      },
      {
        step: 5,
        label: 'Agent computes MtM and forward P&L',
        detail:
          'Strike minus market times remaining volume, summed across the tenor. Sensitivities are computed by repeating the calculation with perturbed inputs.',
      },
      {
        step: 6,
        label: 'Guardrail checks units and direction',
        detail:
          'The platform validates that volumes and prices use consistent units, and that the sign of MtM matches a buy or sell direction. A failed check returns a degraded response rather than an inverted number.',
      },
      {
        step: 7,
        label: 'UI renders the headline, the chart and the sensitivity table',
        detail:
          'No further math in the browser.',
      },
    ],
    glossary: [
      ...pick(['mtm', 'spot_price', 'forward_curve', 'basis_risk', 'guardrail']),
      {
        term: 'Forward P&L',
        definition:
          'The projected profit or loss of a contract across its remaining tenor, valued at the current forward curve. Tells you what the position is worth month by month if the forward curve held.',
      },
      {
        term: 'Strike',
        definition:
          'The fixed price (or formula) in your contract. MtM is essentially the difference between this strike and the market price, multiplied by remaining volume.',
      },
    ],
  },

  forecaster: {
    routeKey: 'forecaster',
    page_title: 'Predictive offtake forecaster',
    purpose:
      'This page predicts how much energy a customer or portfolio of customers will actually consume over the next 12 months. The output is a fan chart: a central forecast surrounded by uncertainty bands. The wider the fan, the less the model trusts itself for that horizon.\n\nThree model classes are available. Residential and SMB uses a regression calibrated to typical metered load shapes. Industrial heatload uses a model that mixes process heat and ambient temperature. Storage cycling uses a model for charge and discharge volumes against a price signal. The model classes themselves are real machine learning models, trained on seed data shipped with the product. The model classes are real, the curves you see are simulated outputs from those models.\n\nBe honest about this: the baseline regression is calibrated on synthetic seed data, not on your real customer telemetry. If you connect a real telemetry feed via the [Energy Data Fabric](/data-fabric), the model will retrain on that and the forecasts will be grounded. Until then, treat the curves as a shape demonstration, not a meter-accurate prediction.',
    sections: [
      {
        title: 'Model class selector',
        what_it_shows:
          'Three options: Residential and SMB, Industrial heatload, Storage cycling. Each switches the underlying ML model and the input features it expects.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The model classes are real and persisted in the [Energy Data Fabric](/data-fabric). Switching just routes the request to a different model. None of them is generated on the fly.',
      },
      {
        title: 'Forecast fan chart',
        what_it_shows:
          'A central forecast line for monthly offtake, surrounded by P10 to P90 bands. The bands widen with horizon to reflect growing uncertainty.',
        agent_slug: 'ciq-offtake-forecaster',
        tools_used: ['code_asset', 'monte_carlo_curve'],
        data_quality: 'agent-simulated',
        layman_note:
          'The central line is the regression model output. The fan around it is a Monte Carlo over the residual distribution from training. Both numbers depend on the training data being representative, which is the synthetic-data caveat at the top.',
      },
      {
        title: 'Driver attribution',
        what_it_shows:
          'A breakdown of how much weather, day of week and price each contributed to the central forecast. Drivers come from SHAP values on the underlying regression.',
        agent_slug: 'ciq-offtake-forecaster',
        tools_used: ['code_asset'],
        data_quality: 'agent-simulated',
        layman_note:
          'A driver of +120 MWh from weather means the model adjusted the baseline up by that amount because of the weather feature. It does not mean weather literally caused 120 MWh.',
      },
      {
        title: 'Capacity factor view',
        what_it_shows:
          'For the storage cycling model, the implied capacity factor: how much of the asset capacity the model expects to use each month.',
        agent_slug: 'ciq-offtake-forecaster',
        tools_used: ['code_asset'],
        data_quality: 'agent-simulated',
        layman_note:
          'A 25% capacity factor means the model expects the asset to run at full output for 25% of the hours in the month, on average. Only shown when the storage cycling model is selected.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/forecaster/run',
        detail:
          'Passes the model class slug, the horizon in months, and any user-supplied overrides for inputs.',
      },
      {
        step: 2,
        label: 'API loads the selected ML model from the data fabric',
        detail:
          'The model artefact is pulled from the local model registry. This is a real persisted regression model, not an LLM. See the [Energy Data Fabric](/data-fabric) for the inventory.',
      },
      {
        step: 3,
        label: 'API forwards to AgentForge via the SDK',
        detail:
          'Calls the ciq-offtake-forecaster agent. The agent wraps the regression model: it formats inputs, calls predict, runs Monte Carlo on the residuals, computes SHAP attribution.',
      },
      {
        step: 4,
        label: 'Agent runs the regression and the Monte Carlo',
        detail:
          'The central forecast is the regression output. The fan bands come from 1,000 simulated residual paths. The SHAP breakdown is a single deterministic call on the regression model.',
      },
      {
        step: 5,
        label: 'UI renders the fan chart and the attribution',
        detail:
          'No further math in the browser. The provenance banner makes clear that the curves are simulated from a model trained on seed data.',
      },
    ],
    glossary: [
      {
        term: 'Offtake',
        definition:
          'How much energy a customer or asset actually takes off the grid over a period, measured in MWh. The opposite of generation. What this page is trying to predict.',
      },
      ...pick(['capacity_factor', 'monte_carlo', 'shap']),
      {
        term: 'Fan chart',
        definition:
          'A forecast plot with a central line surrounded by uncertainty bands (P10 to P90 is typical). The fan widens with horizon because predictions get less certain further out.',
      },
      {
        term: 'ML model (vs LLM agent)',
        definition:
          'An ML model here means a classical machine learning model (regression, random forest, gradient boosting) trained on tabular data and called with predict. An LLM agent is a language model with tools. The forecaster uses an ML model, the Workbench uses both.',
      },
      {
        term: 'Regression vs classification',
        definition:
          'Regression predicts a number (next month MWh). Classification predicts a category (default or not default). The forecaster is regression. The clause risk classifier is classification.',
      },
      {
        term: 'Training set',
        definition:
          'The historical examples the model learned from. For the forecaster, this is synthetic seed data until you connect real telemetry. The model can only be as good as this set.',
      },
    ],
  },

  'data-fabric': {
    routeKey: 'data-fabric',
    page_title: 'Energy data fabric',
    purpose:
      'This page is a registry. It lists every market-data tool an agent in this tenant can call, plus the ML models that are loaded and the recent execution telemetry. Nothing here is a forecast or a valuation. It is just the inventory: what tools exist, whether each one fetches live from a public source or only simulates output, and which ML models are loadable by other pages.\n\nMarket data does not flow through a "connectors" admin UI. It flows through tools registered in the agent runtime under apps/agent-runtime/engine/tools/. If a tool appears in the registry, agents that include it in their YAML config can call it. If an ML model appears here, it is loadable by the [forecaster](/forecaster), the [workbench](/workbench), and valuation.',
    sections: [
      {
        title: 'Market-data tools available to agents',
        what_it_shows:
          'The registry of market-data tools grouped by category (market prices, search and news, filings and registry, credit and rating, weather, compute and explain, extraction). Each tile shows the tool name, a one-line purpose, a status badge (live / simulated / unavailable) and the last-used timestamp when telemetry is available.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Live means the tool fetches from a real public upstream. Simulated means the tool produces output without an external market-data call (pure math or LLM-only). Unavailable means the tool exists but the upstream feed needs a paid subscription this tenant does not have. The footer explains how to add a new tool.',
      },
      {
        title: 'ML model inventory',
        what_it_shows:
          'Every persisted model: name, class (regression, classification, Bayesian, IsolationForest), version, training date, training set size.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'A row here means the model file is on disk and loadable. It does not say anything about whether the model is currently accurate. For that, see [Model Performance](/model-performance).',
      },
      {
        title: 'Execution telemetry',
        what_it_shows:
          'A count of recent agent executions, bucketed by status (completed, failed, running). Useful for spotting whether anything has actually been run lately.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'A high failed count usually means an agent ran out of budget or a tool returned a degraded payload. Drill into a single failed execution to see the tool calls.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/data-fabric/sources',
        detail:
          'A single GET with the user token. Returns models, connections and lineage as JSON.',
      },
      {
        step: 2,
        label: 'API runs SQL against the registry tables',
        detail:
          'No model is loaded and no data feed is hit. This is a pure read of the registry. Refresh times are read from a side table updated by the agents that own the connections.',
      },
      {
        step: 3,
        label: 'UI renders the three panels',
        detail:
          'No further computation in the browser beyond formatting timestamps.',
      },
    ],
    glossary: [
      {
        term: 'ML model (vs LLM agent)',
        definition:
          'An ML model here means a classical machine learning model (regression, random forest, gradient boosting, IsolationForest) trained on tabular data and called with predict. An LLM agent is a language model with tools.',
      },
      {
        term: 'Bayesian model',
        definition:
          'A model that produces a distribution over predictions, not a single point. The output is "the value is most likely 42 but could plausibly be 35 to 50", which makes uncertainty explicit. Used in Mispricing Lens and in some Workbench blocks.',
      },
      {
        term: 'IsolationForest',
        definition:
          'A model that scores how unusual a single data point is compared with the rest of the training data. Used for anomaly detection. It does not predict a value, it flags weirdness.',
      },
      {
        term: 'Training set',
        definition:
          'The historical examples the model learned from. The registry shows the size of this set for each model so you can sanity-check whether a number is built on much data.',
      },
      ...pick(['agent', 'pipeline']),
    ],
  },

  workbench: {
    routeKey: 'workbench',
    page_title: 'Analyst Workbench',
    purpose:
      'The workbench is a feature-attribution playground for the ML models that power forecasting and pricing. You pick one of the registered models, edit its input features by hand, press Run Explain, and the page returns the model\'s prediction plus a per-feature SHAP attribution showing which inputs pushed the prediction up and which pushed it down.\n\nThis is a debugging and trust tool, not a workflow. Nothing trades. Nothing schedules. The point is to answer questions like "if the seasonal heating-degree-day index goes up by 2, how does the offtake model react?" — by varying one feature at a time and reading the attribution.',
    sections: [
      {
        title: 'Model picker',
        what_it_shows:
          'A dropdown of the five registered ML models (offtake residential, offtake industrial, offtake storage cycling, gas-hubs fair-value, power-hubs fair-value) with the family of each model (GradientBoostingRegressor, BayesianRidge, etc).',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'These models are the ones registered in the [Energy Data Fabric](/data-fabric). Pick the model whose prediction you want to interrogate.',
      },
      {
        title: 'Feature input editor',
        what_it_shows:
          'A list of named feature inputs for the selected model with editable numeric values. Defaults to a representative sample so you can immediately press Run; change the numbers to see how the prediction reacts.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The feature names are exactly the inputs the model was trained on. The defaults are a snapshot, not a forecast. You are simulating "what if the inputs looked like this" — the model does not have ground truth here.',
      },
      {
        title: 'Run Explain button',
        what_it_shows:
          'Triggers a POST to /api/contractiq/workbench/explain with the model name and the current feature values. The API runs the model, computes SHAP attributions, returns prediction + per-feature contributions.',
        agent_slug: undefined,
        tools_used: ['ml_model_tool'],
        data_quality: 'real-fetched',
        layman_note:
          'No LLM agent is in the loop. This is a pure ML model invocation. The SHAP attribution is a model-explainability technique — not a forecast and not an LLM judgement.',
      },
      {
        title: 'Prediction value',
        what_it_shows:
          'The single number the model returned for the inputs you typed. Units vary by model (volume for offtake, EUR/MWh for the gas/power fair-values).',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'This is the model\'s output for these specific inputs. Change a feature and re-run to see how it moves.',
      },
      {
        title: 'Feature attributions (SHAP)',
        what_it_shows:
          'A bar list of every input feature with its SHAP value — the directional contribution to the prediction. Positive bars pushed the prediction up. Negative bars pushed it down. The magnitude is the size of the push.',
        agent_slug: undefined,
        tools_used: ['ml_model_tool'],
        data_quality: 'real-fetched',
        layman_note:
          'SHAP comes from cooperative game theory. It distributes the prediction among the input features so the contributions add up to the difference between the model\'s output and its baseline. It is a model-explainability tool, not a causal claim about the world.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects a model and edits features',
        detail:
          'All edits are local until Run Explain is pressed. The model registry that powers the dropdown is loaded once from /api/contractiq/data-fabric/sources.',
      },
      {
        step: 2,
        label: 'POST /api/contractiq/workbench/explain',
        detail:
          'The browser sends the model name and the current feature values. The API loads the trained model, runs prediction, then runs the SHAP explainer.',
      },
      {
        step: 3,
        label: 'Server runs model + SHAP',
        detail:
          'This is a synchronous numpy/scikit-learn call. No agent loop, no LLM call, no streaming. Typical response time is well under a second.',
      },
      {
        step: 4,
        label: 'UI renders prediction + attribution bars',
        detail:
          'Prediction is rendered as a single number. SHAP contributions are rendered as a horizontal bar list, ordered by absolute magnitude.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'guardrail']),
      {
        term: 'ML model (vs LLM agent)',
        definition:
          'The workbench operates on classical ML models — regression and gradient-boosting. These are deterministic given fixed inputs. An LLM agent is a different thing entirely (probabilistic, tool-calling, narrative-producing). The workbench shows only ML models.',
      },
      {
        term: 'SHAP attribution',
        definition:
          'A method from cooperative game theory that distributes a model\'s prediction among its input features so the contributions add up to the gap between the model\'s output and its baseline. Reads as "each feature pushed the prediction up or down by this much".',
      },
      {
        term: 'Feature input',
        definition:
          'A single named value the model was trained to receive. Editing one input and re-running shows the model\'s sensitivity to that input — useful for spotting overweight features or unexpected non-linearities.',
      },
    ],
  },

  'model-performance': {
    routeKey: 'model-performance',
    page_title: 'Model performance and backtesting',
    purpose:
      'This page tells you how well each ML model has actually been performing on held-out data. Pick a model, pick a horizon, see the backtest. Metrics include error on regression models (MAE, RMSE) and AUC and F1 on classification models. For Bayesian models, you also see calibration: how often the realised value fell inside the predicted band.\n\nImportant honesty: these are backtest results from training and holdout data, not live trading P&L. A model that backtests well can still trade badly when the market regime changes. Treat the numbers here as evidence that the model has learned a pattern, not a guarantee that the pattern will hold tomorrow.',
    sections: [
      {
        title: 'Model selector',
        what_it_shows:
          'Dropdown of every model in the [Energy Data Fabric](/data-fabric) inventory. Selecting a model loads its most recent backtest.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The list is the registry. If a model is here, it has been trained at least once. The backtest is from that training run, not from a fresh re-fit on whatever data you might have added since.',
      },
      {
        title: 'Regression metrics',
        what_it_shows:
          'For regression models: MAE (mean absolute error), RMSE (root mean square error) and R-squared on the holdout set.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'An MAE of 50 MWh on a model that predicts monthly offtake means the average prediction was off by 50 MWh in either direction on the holdout. Lower is better. RMSE punishes large errors more harshly than MAE.',
      },
      {
        title: 'Classification metrics',
        what_it_shows:
          'For classification models: AUC (area under the ROC curve), F1, precision and recall on the holdout set. Confusion matrix on demand.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'AUC of 0.5 is a coin flip, 1.0 is perfect. F1 balances precision (when the model says yes, how often is it right) against recall (of all the real yeses, how many did the model catch). Read both, not just one.',
      },
      {
        title: 'Backtest history',
        what_it_shows:
          'A line plot of how the headline metric evolved across past retrainings. Useful for spotting drift: a model that used to MAE 30 and now MAEs 80 is degrading.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Drift here means the data distribution shifted out from under the model. If you see drift, the next step is to retrain on more recent data, not to argue with the metric.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/data-fabric/sources',
        detail:
          'A single GET with the model id and an optional time range. No agent is involved.',
      },
      {
        step: 2,
        label: 'API loads the persisted backtest from the database',
        detail:
          'Backtest results are written at training time and stored alongside the model artefact. The page reads them, it does not recompute them.',
      },
      {
        step: 3,
        label: 'UI renders the metrics and the plots',
        detail:
          'No further math in the browser. The numbers are exactly what was measured at training time.',
      },
    ],
    glossary: [
      {
        term: 'Backtesting',
        definition:
          'Running a model on historical data it has not seen during training, to see how well it would have performed. Tells you whether the model has learned a real pattern or just memorised the training set.',
      },
      {
        term: 'Training set',
        definition:
          'The historical examples the model learned from. Typically the older slice of available data.',
      },
      {
        term: 'Holdout set',
        definition:
          'A slice of historical data deliberately kept out of training, used to measure how the model performs on examples it has not seen. The headline metrics on this page are computed on this set.',
      },
      {
        term: 'AUC / F1',
        definition:
          'Two ways of scoring a classification model. AUC measures how well the model ranks positives above negatives across all thresholds (0.5 random, 1.0 perfect). F1 is the harmonic mean of precision and recall at a chosen threshold.',
      },
      {
        term: 'Regression vs classification',
        definition:
          'Regression predicts a number. Classification predicts a category. They use different metrics, so this page shows different panels depending on the model class.',
      },
      {
        term: 'Bayesian model',
        definition:
          'A model that produces a distribution over predictions, not a single point. Performance is measured by calibration: do the predicted uncertainty bands actually contain the realised value at the claimed frequency.',
      },
      {
        term: 'IsolationForest',
        definition:
          'An anomaly detection model. Performance is measured by how well its anomaly score separates real anomalies from normal points in the holdout, typically using AUC.',
      },
    ],
  },

  risk: {
    routeKey: 'risk',
    page_title: 'Market risk — VaR, CVaR and correlations',
    purpose:
      'This page puts a dollar number on the market risk you are running across the precious-metals book. It answers two questions. How much could the book lose on a normal bad day (VaR). How bad does it get on the days that exceed that threshold (CVaR). It also shows how the assets move together (correlation matrix) and what a proposed new position would add (marginal VaR).\n\nThe returns going into the calculation are real — they come from public LBMA gold and silver fixes and LPPM platinum and palladium fixes, pulled by the market-data adapters in the API. The VaR percentile itself is a statistical model output, not a forecast. A 95% one-day VaR of $250k means that across the simulated or resampled distribution, the 95th percentile loss is $250k. It does NOT mean "you will lose $250k tomorrow" and it does not anticipate moves outside the calibration window. Real markets routinely produce shocks that were not in the last 250 days.',
    sections: [
      {
        title: 'Preset VaR / CVaR runs',
        what_it_shows:
          'One-click presets for gold, silver, platinum and palladium at $5-10M notional, one-day or ten-day horizon, 95% or 99% confidence. Each run lists var_usd, cvar_usd, var_pct, cvar_pct and the number of return observations behind it. The exposure base for each row is the preset notional.',
        agent_slug: 'contractiq-risk-calculator',
        tools_used: ['market_data', 'market_data', 'market_data', 'market_data', 'code_asset', 'code_asset', 'code_asset'],
        data_quality: 'mixed',
        layman_note:
          'The returns are real prices published by LBMA / LPPM. The VaR number is what a model said about those returns — a statistical estimate, not a forecast of tomorrow. Switching method between parametric, historical and filtered-historical can move the number by 20-40% on the same returns, which is why each row shows the method it used.',
      },
      {
        title: 'Correlation matrix',
        what_it_shows:
          'A grid of pairwise correlations across the four metals over the last 120 days, computed with EWMA (exponentially-weighted moving average, decay 0.94). Values close to 1 mean the metals moved together. Values close to 0 mean they drifted independently.',
        agent_slug: 'contractiq-correlations',
        tools_used: ['market_data', 'market_data', 'market_data', 'market_data', 'code_asset'],
        data_quality: 'mixed',
        layman_note:
          'Correlations are real arithmetic on real returns. The number is right for the window. But correlations are not stable — in a crisis, things that looked uncorrelated suddenly all go down together. Use the matrix to check whether your positions diversify each other under normal conditions, not as a guarantee in a stress event.',
      },
      {
        title: 'Marginal VaR (agent available, not yet on this page)',
        what_it_shows:
          'For a proposed new position, the contractiq-marginal-var-analyzer agent can compute base_var_usd, new_var_usd and marginal_var_usd — the dollar amount of VaR the new position would add. The agent is wired in the backend (POST /api/contractiq/risk/marginal-var) but no UI control invokes it from this page yet.',
        agent_slug: 'contractiq-marginal-var-analyzer',
        tools_used: ['code_asset', 'monte_carlo_curve'],
        data_quality: 'degraded',
        layman_note:
          'A positive marginal VaR means the trade would increase overall risk. A negative one would reduce risk (a hedge). This page does not currently expose a "what if I added this position?" widget — call the agent directly via the API if you need the number now.',
      },
      {
        title: 'Run history',
        what_it_shows:
          'Every VaR run is persisted with a calc_signature (a SHA-256 of the inputs and the observation count) so two identical inputs return the same hash. Use the signature to confirm a number you quoted earlier came from the same data.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The signature is not a "true value". It is a checksum. Same inputs → same hash. Different inputs → different hash. Useful for audit, not for risk.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/risk/var (or /portfolio/var, /marginal-var, /correlations)',
        detail:
          'The page passes the source slug (e.g. lbma_gold_fix), notional, confidence and horizon. The router validates and resolves the returns series.',
      },
      {
        step: 2,
        label: 'API fetches the real returns series via market-data adapters',
        detail:
          'Adapter calls LBMA / LPPM for the configured history (default 250 trading days), caches in the database, and hands the resolved series to the agent. The agent never talks to the data sources directly.',
      },
      {
        step: 3,
        label: 'Router delegates the math to an Abenix agent',
        detail:
          'contractiq-risk-calculator runs the chosen method (parametric, historical, filtered-historical, or Monte Carlo). contractiq-correlations builds the EWMA matrix. contractiq-marginal-var-analyzer computes the incremental VaR for a proposed position. The thin router pattern keeps audit and governance with the agent runtime.',
      },
      {
        step: 4,
        label: 'Result is persisted with a calc_signature',
        detail:
          'Inputs are hashed (SHA-256 over the canonical JSON) so identical inputs produce an identical signature. The VaR row is written to ContractIQRiskRun for replay and audit.',
      },
      {
        step: 5,
        label: 'UI renders the dollar numbers, the correlation grid and the run history',
        detail:
          'No further math in the browser. The percentages shown are exactly what the agent returned, formatted.',
      },
    ],
    glossary: pick([
      'var',
      'cvar',
      'parametric_var',
      'historical_var',
      'monte_carlo_var',
      'monte_carlo',
      'correlation_matrix',
      'marginal_var',
      'exposure_base',
      'guardrail',
    ]),
  },

  recommendations: {
    routeKey: 'recommendations',
    page_title: 'Cross-signal recommendations',
    purpose:
      'This page surfaces actionable recommendations across the portfolio — trade, hedge or monitor — by combining live counterparty tiers, forward-price expectations and unacknowledged compliance alerts. Each card cites the underlying signals so you can see why it was raised.\n\nThe engine does not invent recommendations. If an upstream agent has no live data, the dependent recommendation is dropped rather than padded with filler. The needs_configuration banner at the top names any upstream agent that is missing credentials or returned no usable result.',
    sections: [
      {
        title: 'Recommendation cards',
        what_it_shows:
          'A ranked list of recommendations grouped by category (trade, hedge, monitor) with an estimated impact in EUR, a confidence number, and the evidence pulled from upstream agents. Sorted by impact_eur descending.',
        agent_slug: 'ciq-recommendation-engine',
        tools_used: ['invoke_agent', 'invoke_agent', 'database_query', 'database_query'],
        data_quality: 'mixed',
        layman_note:
          'The impact_eur is a model estimate built from the price and volume forecasts of the upstream agents. It is not a quote, not a guaranteed P&L. The confidence number is the engine\'s own assessment of how well-grounded the recommendation is in the signals it found, not a probability of being right.',
      },
      {
        title: 'Upstream signal summary',
        what_it_shows:
          'A banner listing which live sources fed this run (e.g. price-engine, offtake-forecaster) and which ones were skipped because of missing configuration or empty results.',
        agent_slug: 'ciq-recommendation-engine',
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'If a source is in needs_configuration, recommendations that depended on it are NOT shown. The engine degrades honestly rather than emitting half-supported suggestions.',
      },
      {
        title: 'Evidence drawer',
        what_it_shows:
          'Per-card detail: the exact values returned by ciq-offtake-forecaster and ciq-price-engine, the counterparty tier, and any compliance alerts that contributed.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'This is the audit trail. Click into a card to see the raw inputs the engine used. If a number on the card surprises you, the drawer is where you check whether the input was reasonable.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser POSTs /api/contractiq/recommendations/run with an empty body',
        detail:
          'The API takes tenant_id from the JWT claim, not the body. The browser only sends its bearer token. No streaming.',
      },
      {
        step: 2,
        label: 'API forwards to ciq-recommendation-engine via the Abenix SDK',
        detail:
          'The engine fans out to ciq-offtake-forecaster (volume expectations) and ciq-price-engine (forward prices), reads counterparty tiers from the tenant tables, and pulls unacknowledged compliance alerts.',
      },
      {
        step: 3,
        label: 'Engine ranks by estimated impact_eur',
        detail:
          'For each candidate it computes an impact in EUR from the price-volume signals, attaches the evidence array, and assigns a confidence based on how many independent sources agreed.',
      },
      {
        step: 4,
        label: 'Recommendations whose dependencies failed are dropped',
        detail:
          'No fallback synthesis. If ciq-price-engine returned nothing for a hub, every recommendation tied to that hub is removed from the list and the hub is named in summary.needs_configuration.',
      },
      {
        step: 5,
        label: 'UI renders cards with filter chips and an evidence drawer',
        detail:
          'Filtering is client-side over the returned list. No further math in the browser.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'forward_curve', 'guardrail']),
      {
        term: 'Recommendation engine',
        definition:
          'The ciq-recommendation-engine agent that fans out to price, volume, counterparty and compliance sources, then ranks candidate actions by an estimated EUR impact. It does not invent recommendations — if an upstream source has no data, the dependent card is dropped rather than padded.',
      },
      {
        term: 'Signal',
        definition:
          'A single input the engine reads from an upstream agent or table: a forward price from ciq-price-engine, a volume expectation from ciq-offtake-forecaster, a counterparty tier, an open compliance alert. Each card on this page lists the signals that fed it.',
      },
      {
        term: 'Confidence score',
        definition:
          'The engine\'s own assessment of how well-grounded a recommendation is in the signals it found. Driven by how many independent sources agreed. It is NOT a probability that the action will pay off — treat it as a sort key, not a forecast.',
      },
      {
        term: 'Dismissal',
        definition:
          'A UI action to hide a recommendation from the active list. The row stays in the database for audit and never re-appears even if the same conditions trigger again on a later run.',
      },
    ],
  },

  insights: {
    routeKey: 'insights',
    page_title: 'Insights hub',
    purpose:
      'This is the entry point to the nine Insights workflows. Each tile launches a separate Abenix agent that does one job — generate the morning briefing, draft a renewal packet, scan for force-majeure triggers, reconcile an invoice, group contracts into families, detect clause anomalies, diff two contract versions, run a stress test, or recommend hedges.\n\nThe counters on each tile (briefings today, renewals upcoming, anomalies active, and so on) are simple aggregates over the local Insights tables. Clicking a tile takes you into the workflow page where the underlying agent actually runs.',
    sections: [
      {
        title: 'Workflow tiles',
        what_it_shows:
          'Nine tiles grouped into Daily, On-demand and Contracts. Each tile names the pipeline that powers it and shows a counter (e.g. "3 renewals in 180 days") sourced from the Insights overview endpoint.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The hub itself does not call any agent. It just counts rows. The agents run when you open a tile.',
      },
      {
        title: 'Pipeline labels',
        what_it_shows:
          'Each tile prints the slug of the agent it launches (contractiq-executive-briefing, contractiq-renewal-copilot, contractiq-force-majeure-monitor, contractiq-settlement-reconciler, contractiq-clause-anomaly, contractiq-version-diff, contractiq-stress-test, contractiq-hedge-advisor, contractiq-clause-benchmarker).',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'These names are the actual agent slugs registered in AgentForge. Useful when you want to inspect a run in the executions drawer.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/insights/briefing/today',
        detail:
          'A single GET returns the counts: briefings_today, renewals_upcoming, fm_notices_pending, reconciliations_total, families_total, anomalies_active, diffs_total, stress_tests_total, hedge_recs_total, benchmarks_total.',
      },
      {
        step: 2,
        label: 'API runs aggregate SQL across the Insights tables',
        detail:
          'No agent on this endpoint. The hub is pure read-side.',
      },
      {
        step: 3,
        label: 'UI renders tiles with counters',
        detail:
          'No further fetches until the user clicks a tile.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'agentic_workflow']),
      {
        term: 'Insights hub',
        definition:
          'The landing tile grid at /insights. It does not run any agent itself — it counts rows in the local Insights tables and routes the user to the workflow page that owns each one. Agents only run when you click into a tile.',
      },
      {
        term: 'Daily vs on-demand workflow',
        definition:
          'Daily workflows (briefing, force-majeure monitor) are meant to be run every morning on the whole portfolio. On-demand workflows (renewal copilot, version diff, stress test, hedge advisor, anomaly detector, clause benchmarker) are run when you pick a specific contract and ask for them.',
      },
      {
        term: 'Contract intelligence',
        definition:
          'The umbrella label for the workflows that read your already-extracted clauses and return a structured judgement: anomaly scores, renewal packets, family groupings, force-majeure triggers. They do not re-parse the PDF — they read what the [ingest pipeline](/upload) already stored.',
      },
      {
        term: 'Anomaly detection',
        definition:
          'The [clause anomaly](/insights/anomalies) workflow that ranks clauses against the rest of your portfolio using an LLM-as-judge. Produces a relative ordering inside your book, not an absolute measurement.',
      },
    ],
  },

  'insights-briefing': {
    routeKey: 'insights-briefing',
    page_title: 'Daily executive briefing',
    purpose:
      'A morning summary of the portfolio. One headline, a short markdown body, the key metrics for the day, and the top action items. It is meant to be readable on a phone over coffee.\n\nThe briefing is generated by an LLM agent (contractiq-executive-briefing) that is given a structured portfolio context — contract list, statuses, counterparties, capacity, risk scores, upcoming events — and asked to summarise. The numbers in metrics are pulled from your real contracts. The narrative around them is the model\'s prose. Treat the prose as a draft to scan, not a verbatim source of truth — re-check any specific number against the portfolio table before sending the briefing on to anyone else.',
    sections: [
      {
        title: 'Headline and body',
        what_it_shows:
          'A one-line headline and a markdown body that walks through what changed overnight, what crossed an alert threshold, and what you should look at first.',
        agent_slug: 'contractiq-executive-briefing',
        tools_used: ['database_query', 'llm_call'],
        data_quality: 'mixed',
        layman_note:
          'The body is LLM-written prose. The model only sees the structured portfolio context — it cannot fabricate a contract that does not exist, but it can phrase a true fact in a misleading way. Read it like a draft from an analyst, not a published report.',
      },
      {
        title: 'Metrics block',
        what_it_shows:
          'The numerical highlights for the day (e.g. count of analysed contracts, average risk score, expiries in the next 7/30/90 days).',
        agent_slug: 'contractiq-executive-briefing',
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These numbers come straight from the contracts database via the portfolio context builder. No model invention.',
      },
      {
        title: 'Top actions',
        what_it_shows:
          'A short list of suggested actions: which contracts to look at, which alerts to clear, which renewals to prepare.',
        agent_slug: 'contractiq-executive-briefing',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'The actions are the model\'s suggestions based on the portfolio context. Sensible defaults, but not a workflow plan. Use the action items as prompts, not as instructions.',
      },
      {
        title: 'Run cost and timing',
        what_it_shows:
          'cost_usd and duration_ms from the underlying agent execution, so you can see what the briefing actually cost to produce.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Real numbers from the AgentForge execution record.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser POSTs /api/contractiq/insights/briefing/generate',
        detail:
          'The page passes an optional focus prompt. The router creates a ContractIQBriefing row with status=running and then calls the agent.',
      },
      {
        step: 2,
        label: 'API builds portfolio context from the contracts DB',
        detail:
          '_build_portfolio_context walks ContractIQContract + ContractIQEvent and produces a text summary the agent can read. This is the only thing the agent sees about your portfolio.',
      },
      {
        step: 3,
        label: 'API calls contractiq-executive-briefing via the Abenix SDK',
        detail:
          'The agent returns a JSON object with headline, body_markdown, metrics and top_actions. The router parses the JSON, with a repair pass if the first response was not valid JSON.',
      },
      {
        step: 4,
        label: 'Result is persisted on the ContractIQBriefing row',
        detail:
          'Status flips to completed (or failed with an error_message if parsing failed). Cost and duration are recorded.',
      },
      {
        step: 5,
        label: 'UI renders the briefing and lists prior briefings',
        detail:
          '/briefing/today returns the most recent one, /briefing/history returns the last N. No further model calls.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'guardrail']),
      {
        term: 'Daily briefing',
        definition:
          'The morning summary produced by the contractiq-executive-briefing agent. One row per run is stored in ContractIQBriefing with status, cost and duration. /briefing/today returns the most recent one, /briefing/history returns the last N.',
      },
      {
        term: 'Executive summary',
        definition:
          'The headline + markdown body block at the top of the briefing. LLM-written prose grounded in the structured portfolio context. Re-check any specific number against the portfolio table before forwarding — the prose can phrase a true fact in a misleading way.',
      },
      {
        term: 'Force majeure (in briefing)',
        definition:
          'A clause category that excuses non-performance under defined extreme events (war, natural disaster, declared epidemic). When the [force-majeure monitor](/insights/force-majeure) flags a trigger overnight, the briefing surfaces it in top_actions so the recipient knows to look at it first.',
      },
      {
        term: 'Run cost and duration',
        definition:
          'cost_usd and duration_ms read from the AgentForge execution record for this briefing run. Real numbers, not an estimate. Useful for sanity-checking the bill against expected token use on the chosen model.',
      },
    ],
  },

  'insights-anomalies': {
    routeKey: 'insights-anomalies',
    page_title: 'Clause anomaly detector',
    purpose:
      'This page flags clauses in your portfolio that look unusual compared to the rest. It is built for the situation where you have hundreds of contracts and a small redlining team — you cannot read every clause yourself, but you can pay attention to the ones that stand out.\n\nThe detection is run by an LLM acting as a judge. The agent reads your portfolio of extracted clauses, compares them against each other within the same clause taxonomy bucket (payment, termination, indemnity, and so on), and returns an anomaly_score per flagged clause. The score is a relative ranking inside your portfolio, not an absolute measurement. A clause with score 0.85 is more unusual than one at 0.6 according to the model, but a different model run could shift the values. Use the ordering, not the absolute number.',
    sections: [
      {
        title: 'Pre-flight: enough clauses to compare?',
        what_it_shows:
          'If you have fewer than 5 extracted clauses across the portfolio the page reports "insufficient_clauses" rather than running the scan. The agent needs a cohort to compare against.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Below the threshold there is nothing useful to say. Upload and extract more contracts first.',
      },
      {
        title: 'Anomaly cards',
        what_it_shows:
          'Each flagged clause shows an anomaly_score (0-1, higher = more unusual), a severity label, a short explanation, and a benchmark summary of what the typical clause in this category looks like.',
        agent_slug: 'contractiq-clause-anomaly',
        tools_used: ['database_query', 'llm_call'],
        data_quality: 'agent-simulated',
        layman_note:
          'The score is the model\'s opinion of "how far from normal" the clause is. It is NOT an objective measurement. If you rescan the same portfolio later, scores can shift by a few percent. Trust the relative ordering and the explanation more than the raw number.',
      },
      {
        title: 'Severity and dismiss',
        what_it_shows:
          'Each anomaly is tagged info / warning / critical and can be dismissed by the user. Dismissed rows are hidden from the active list but kept in the database for audit.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Severity is the agent\'s call, not a regulatory grade. Dismissing is a UI action — no model involved.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser POSTs /api/contractiq/insights/anomalies/scan',
        detail:
          'The router first counts the user\'s extracted clauses. If below 5 it returns "insufficient_clauses" without calling the agent.',
      },
      {
        step: 2,
        label: 'API calls contractiq-clause-anomaly via the Abenix SDK',
        detail:
          'The agent queries the portfolio\'s clauses, groups them by clause taxonomy bucket, and asks an LLM to rank within each bucket how unusual each clause is relative to the others.',
      },
      {
        step: 3,
        label: 'Router validates each flagged ID against the database',
        detail:
          'Any clause_id or contract_id the agent quoted that does not belong to the user is dropped. The count of dropped IDs is logged but not surfaced in the UI.',
      },
      {
        step: 4,
        label: 'Surviving anomalies are persisted to ContractIQClauseAnomaly',
        detail:
          'Each row stores the score, severity, explanation and benchmark summary. Failures during commit are caught per-row so a single bad row does not kill the whole scan.',
      },
      {
        step: 5,
        label: 'UI renders the cards sorted by anomaly_score descending',
        detail:
          'Dismissed rows are hidden by default. Cost and timing of the scan are surfaced for audit.',
      },
    ],
    glossary: pick([
      'anomaly_score',
      'clause_taxonomy',
      'llm_as_judge',
      'agent',
      'guardrail',
    ]),
  },

  'insights-stress-test': {
    routeKey: 'insights-stress-test',
    page_title: 'Stress test simulator',
    purpose:
      'This page runs a Monte Carlo stress test against a single contract or the whole portfolio. The point is to answer "what would happen to NPV if power prices dropped 30% and FX shifted 15%?" without trading anything in markets.\n\nEverything on this page is a simulation. The shocks (price down 30%, FX up 15%, both at once) are inputs you choose. The contract cashflows are recomputed under each random draw. Nothing real happens — no trade, no settlement, no money moves. The output is "if reality looked like this draw, NPV would be X". The agent runs the requested number of iterations (100 to 10,000), then summarises the distribution at the 5th, 50th and 95th percentiles, plus VaR_95 and expected shortfall.',
    sections: [
      {
        title: 'Scenario parameter form',
        what_it_shows:
          'Inputs for the scope (single contract or portfolio), the iteration count (clamped to 100-10,000), the shock ranges (e.g. power_price_shock_pct = [-30, 30]) and a human label for the run.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'You define the experiment here. The ranges are inputs to a random draw, not predictions.',
      },
      {
        title: 'Distribution summary',
        what_it_shows:
          'Base NPV (no shock), then p5 / p50 / p95 NPV across the simulated runs. p5 is the 5th percentile (a bad day), p95 is the 95th (a good day). VaR_95 is "5% of runs lost more than this".',
        agent_slug: 'contractiq-stress-test',
        tools_used: ['monte_carlo_curve', 'financial_calculator'],
        data_quality: 'agent-simulated',
        layman_note:
          'Every number on this card is a simulation output, not a market price. The simulation drew thousands of random shock combinations from the ranges you specified, recomputed NPV under each, and read the percentiles off the result. Same inputs + same random seed → same numbers. Without a fixed seed, two runs can differ by a few percent.',
      },
      {
        title: 'Worst-case scenarios',
        what_it_shows:
          'The specific shock combinations that produced the worst NPVs across the run. Useful as a "what would have to happen for the book to lose $X" diagnostic.',
        agent_slug: 'contractiq-stress-test',
        tools_used: ['scenario_planner'],
        data_quality: 'agent-simulated',
        layman_note:
          'These are the random draws that hurt the most, not predictions that they will happen. Useful for naming the kind of move that would cause real pain.',
      },
      {
        title: 'Narrative summary',
        what_it_shows:
          'A short markdown writeup of what the test found, generated by the agent based on the numerical outputs.',
        agent_slug: 'contractiq-stress-test',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Prose written by the model around the real distribution. The numbers it references are accurate. Treat the framing as a draft narrative, not an official commentary.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser POSTs /api/contractiq/insights/stress-test with scope, contract_id, iterations and scenario_params',
        detail:
          'The router validates ownership of the contract (if scope=single), clamps iterations to 100-10,000, and creates a ContractIQStressTest row with status=running.',
      },
      {
        step: 2,
        label: 'API calls contractiq-stress-test via the Abenix SDK (600s timeout)',
        detail:
          'The agent draws iterations random shock vectors from the ranges, recomputes contract NPV under each, and assembles the distribution.',
      },
      {
        step: 3,
        label: 'Agent returns the percentiles, VaR_95, expected shortfall and the worst-case shock combos',
        detail:
          'The router parses the JSON and writes the fields onto the ContractIQStressTest row.',
      },
      {
        step: 4,
        label: 'Result is persisted with run cost',
        detail:
          'Status flips to completed (or failed with the raw output truncated to 500 chars if the agent returned bad JSON).',
      },
      {
        step: 5,
        label: 'UI renders the distribution and the worst-case table',
        detail:
          'No further math in the browser. The numbers are exactly what the agent returned.',
      },
    ],
    glossary: pick([
      'monte_carlo',
      'stress_scenario',
      'var',
      'cvar',
      'mtm',
      'agent',
    ]),
  },

  'insights-benchmark': {
    routeKey: 'insights-benchmark',
    page_title: 'Clause benchmarking',
    purpose:
      'This page tells you where a specific clause sits compared to the rest of the market — or more precisely, compared to the seeded benchmark corpus the platform was loaded with. You pick a clause out of one of your contracts, and the agent returns a percentile, a peer summary and an explanation of how this clause compares to typical language for the same category.\n\nBe explicit about what the corpus is. The benchmark corpus is a fixed set of clauses loaded at platform seed time — not a live market feed. If the corpus is small, or skewed toward a specific industry, the percentile is only meaningful relative to that sample. A clause at the 90th percentile of a 200-clause corpus is not the same as the 90th percentile of the universe. Read the benchmark summary card carefully — it tells you how many comparable clauses the corpus had.',
    sections: [
      {
        title: 'Clause selector',
        what_it_shows:
          'A picker to choose a clause out of one of your contracts (filtered by category — payment, termination, liability and so on).',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The clauses listed here are the ones the extraction pipeline pulled out of your uploaded contracts. Pick one, then run the benchmark.',
      },
      {
        title: 'Percentile and peer summary',
        what_it_shows:
          'A percentile ranking of the clause inside the corpus for its category, plus a short summary of what the typical clause in that bucket looks like (cap amount, notice period, exclusions and so on).',
        agent_slug: 'contractiq-clause-benchmarker',
        tools_used: ['database_query', 'llm_call'],
        data_quality: 'mixed',
        layman_note:
          'The percentile compares your clause against the seeded corpus only. If the corpus has 200 liability caps and yours sits above 180 of them, you are at the 90th percentile. That is not the same as "90th percentile of all liability caps in the world".',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser POSTs /api/contractiq/insights/benchmarks/run with a clause_id',
        detail:
          'The router verifies the clause belongs to the user, fetches the clause text and category, and creates a ContractIQClauseBenchmark row.',
      },
      {
        step: 2,
        label: 'API builds the benchmark context from the seeded corpus',
        detail:
          '_build_benchmark_context pulls the corpus rows for the matching category and hands them, along with the target clause, to the agent.',
      },
      {
        step: 3,
        label: 'API calls contractiq-clause-benchmarker via the Abenix SDK',
        detail:
          'The agent computes a percentile against the corpus, summarises the typical peer language, and writes an outlier explanation when the clause is in the tails.',
      },
      {
        step: 4,
        label: 'Result is persisted on the ContractIQClauseBenchmark row',
        detail:
          'Latest-wins per clause — listing endpoints return only the most recent benchmark per clause.',
      },
      {
        step: 5,
        label: 'UI renders the percentile, peer summary and corpus size',
        detail:
          'No further math in the browser.',
      },
    ],
    glossary: pick([
      'benchmark_percentile',
      'clause_taxonomy',
      'llm_as_judge',
      'agent',
      'guardrail',
    ]),
  },

  'commodities-forward-pipeline-gas': {
    routeKey: 'commodities-forward-pipeline-gas',
    page_title: 'Forward fair-value · Pipeline Gas',
    purpose:
      'This page builds a forward fair-value curve for pipeline natural gas. The default benchmark is TTF (the Dutch Title Transfer Facility, the European wholesale hub priced in EUR per megawatt-hour). NBP (the UK National Balancing Point, priced in p/therm) and Henry Hub (the US Gulf Coast hub priced in USD per MMBtu) are also wired. Pick the hub from the selector at the top.\n\nA forward curve is a list of prices agreed today for delivery on future dates. A fair-value curve is the same list but anchored to a live spot print and shaped by a model that simulates the realistic range of where each tenor could land. Reading the slope tells you whether the market expects gas to rise (contango — usually summer storage build) or fall (backwardation — usually a winter scarcity unwind).\n\nThe spot anchor is fetched live from a public feed. The simulated band around it is honest about being a model output — the page prints a provenance row underneath every chart so you know which dots are real and which dots are simulated. The agent will not invent a spot if the fetch failed. A deterministic canonical-anchor guardrail validates that the median of the simulated band sits close enough to the fetched anchor before the curve is allowed to render.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'A dropdown to pick the hub (TTF, NBP, Henry Hub) and the tenor span (front-month through cal+2). The selection is persisted in the URL as ?commodity=pipeline_gas&hub=ttf so you can share the exact view.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No agent runs at this step. The selectors just compose the request the page will send next.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'A single button that fires the GET /api/contractiq/commodities/{slug}/forward/run call with the selectors above. While the agent is running the button shows a spinner and the chart shows a skeleton.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The CTA is also debounced — repeated clicks do not stack a queue of agent runs.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The current front-month price in the native unit (EUR/MWh for TTF, p/therm for NBP, USD/MMBtu for Henry Hub), the last refresh timestamp, and the data source. This is the live print everything else hangs off.',
        agent_slug: 'contractiq_pipeline_gas_fairvalue',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'A real fetch from Yahoo Finance. If Yahoo did not respond, the card shows "data unavailable" rather than a fabricated number. The rest of the page is gated on this anchor existing.',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'The forward curve drawn as a fan: the dark line is the median expected price across simulated paths (P50), the shaded band is the 80% confidence interval (P10 to P90). Tenors span front-month through cal+2.',
        agent_slug: 'contractiq_pipeline_gas_fairvalue',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'The P50 line is anchored to the real spot. The band around it is simulated — the agent computed realized volatility from recent prints, then ran a Monte Carlo across the tenor to sketch the realistic range. The band is a model output, not a market quote.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'A short list of current news drivers (Norwegian flow outages, EU storage levels, LNG send-out, Russian pipeline flows) with citation links. The list is regenerated each run.',
        agent_slug: 'contractiq_pipeline_gas_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Headlines come from a real web search at the time of the run. The agent does not invent drivers. If search returned nothing, the panel is empty.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'A short markdown summary of the curve shape and the top driver, plus a coloured strip naming the spot source, the model used for the band, and a flag if the canonical-anchor guardrail had to correct the median.',
        agent_slug: 'contractiq_pipeline_gas_fairvalue',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Read the banner before quoting a tenor price. The same chart is real on the front and modelled on the back.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity=pipeline_gas and hub',
        detail:
          'The selector composes ?commodity=pipeline_gas&hub=ttf into the URL. No network call yet.',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'The browser sends the request with the user token in the Authorization header. The API does not compute the curve itself.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'The API calls the contractiq_pipeline_gas_fairvalue agent with the hub slug. The SDK call waits up to 120 seconds.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance, realized_vol_calc, monte_carlo_curve, tavily_search',
        detail:
          'yahoo_finance pulls the live front-month print. realized_vol_calc computes the recent realised volatility. monte_carlo_curve runs simulated paths calibrated to that volatility to fill out P10/P50/P90 per tenor. tavily_search returns current driver headlines.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'The platform checks that the P50 at the front-month tenor is within a tolerance of the real fetched spot. If the agent drifted, the median is snapped to the anchor and a corrected flag is set on the provenance banner.',
      },
      {
        step: 6,
        label: 'UI renders curve, drivers and provenance',
        detail:
          'The chart is a direct plot of the curve array. The drivers list is a direct render of the search hits. The summary markdown and provenance banner sit underneath.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_price', 'spot_anchor', 'monte_carlo', 'contango', 'backwardation', 'basis_risk', 'ttf', 'p10_p50_p90', 'seasonality']),
      {
        term: 'NBP',
        definition:
          'National Balancing Point. The UK virtual wholesale gas hub. Prices are quoted in pence per therm. NBP and TTF track each other closely most of the time, with basis driven by Interconnector pipeline flows.',
      },
      {
        term: 'Henry Hub',
        definition:
          'The US natural gas benchmark, a physical pipeline interchange in Erath, Louisiana. NYMEX futures settle against it. Prices are quoted in USD per million British thermal units.',
      },
    ],
  },

  'commodities-forward-lng': {
    routeKey: 'commodities-forward-lng',
    page_title: 'Forward fair-value · LNG (JKM)',
    purpose:
      'This page builds a forward fair-value curve for spot LNG against the JKM benchmark. JKM (the Japan-Korea Marker, published by S&P Global Platts) is the North Asia spot LNG reference, priced in USD per MMBtu. It is the benchmark most active LNG cargoes price against, even those delivered outside Asia.\n\nThe curve shows where the market expects JKM to land across forward delivery months. Reading the slope tells you whether North Asia winter is being priced as tight (steep contango into Q4/Q1) or loose (flat to backwardated). JKM trades a real basis to TTF (Dutch gas) — the basis widens when one basin pulls cargoes from the other.\n\nThe spot anchor is a live fetch. The fan around it is a calibrated Monte Carlo — the agent estimates realised vol from recent JKM prints and projects the realistic range. The guardrail re-anchors the median to the fetched spot if the agent drifted. Provenance is printed on every render so you know which numbers came from the market and which from the simulation.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'A dropdown to confirm commodity=lng and the basin (default North Asia / JKM). The route is persisted as ?commodity=lng.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The selector exists for parity with the other commodity pages. North Asia / JKM is currently the only wired basin.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'Fires the GET /api/contractiq/commodities/{slug}/forward/run?commodity=lng call. Debounced.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No agent until the button is pressed.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The current JKM front-month print in USD/MMBtu, last refresh timestamp and the data source.',
        agent_slug: 'contractiq_lng_fairvalue',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'Real fetch from Yahoo Finance (JKM futures proxy). If the fetch failed, the card prints "data unavailable" and the rest of the page degrades gracefully.',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'A forward fan from front-month through cal+2, with the P50 line anchored to the real spot and the P10 to P90 band drawn from simulated paths.',
        agent_slug: 'contractiq_lng_fairvalue',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'Anchor real, band agent-simulated via Monte Carlo. The band widens with tenor because the model is less certain further out.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'Current LNG headlines (US export terminal status, Qatar liftings, Asian heatwave demand, Japanese reactor restarts). Each item links back to the source article.',
        agent_slug: 'contractiq_lng_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Real web search results. Empty if search returned nothing.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'Short markdown writeup of the curve shape and the dominant driver, plus the provenance strip naming the spot source and the model behind the band.',
        agent_slug: 'contractiq_lng_fairvalue',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Prose grounded in the structured curve. Always check the cited spot against the anchor card before quoting.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity=lng',
        detail:
          'URL becomes /commodities/forward?commodity=lng. Browser renders the selectors.',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'Single GET with the user token. No streaming.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'The API calls contractiq_lng_fairvalue and waits for the result.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance, realized_vol_calc, monte_carlo_curve, tavily_search',
        detail:
          'Yahoo for JKM spot. Realised-vol calc on the recent print history. Monte Carlo to fan out the curve. Tavily for current driver headlines.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'P50 at the front month is checked against the real fetched spot. If it drifted, the median is snapped back and a corrected flag is set.',
      },
      {
        step: 6,
        label: 'UI renders curve + drivers + provenance',
        detail:
          'No further math in the browser. The chart is a direct render of the curve array.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_anchor', 'jkm', 'ttf', 'monte_carlo', 'contango', 'backwardation', 'basis_risk', 'p10_p50_p90']),
      {
        term: 'DES',
        definition:
          'Delivered Ex-Ship. The most common LNG cargo delivery basis — the seller is responsible for the cargo until it reaches the buyer\'s receiving terminal. Most JKM-linked cargoes are priced DES into Japan or Korea.',
      },
    ],
  },

  'commodities-forward-power': {
    routeKey: 'commodities-forward-power',
    page_title: 'Forward fair-value · Power',
    purpose:
      'This page builds a forward fair-value curve for wholesale power. The region selector covers DE (German base on EPEX), FR (French base on EPEX), NORDICS (system price on Nord Pool), ERCOT (North Hub day-ahead) and PJM (Western Hub day-ahead). Each region trades in its native unit — EUR/MWh in Europe, USD/MWh in the US.\n\nA power forward curve is shaped by very different drivers than gas. Renewable build-out and capacity factor changes shift the level. Thermal fuel and carbon costs (gas + EUA in Europe, gas + coal in PJM) set the variable cost stack. Demand seasonality (summer cooling in Texas, winter heating in Europe and the Nordics) drives the peakiness. The agent reads recent prints, computes realised vol, and projects a Monte Carlo fan.\n\nThe spot anchor is the most recent day-ahead clear for the region. The fan around it is a simulated band. The deterministic guardrail re-anchors the P50 to the real fetched clear before the chart renders. Provenance is printed underneath the chart on every run.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'A dropdown to confirm commodity=power and the region (DE, FR, NORDICS, ERCOT, PJM). Sub-selector for base vs peak block. URL becomes ?commodity=power&region=de&block=base.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Block selection matters — peak prices can be 1.5-3x the base in summer-peaking grids like ERCOT.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'Fires the agent run. Debounced. Shows a spinner while the curve builds.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No execution until the button is pressed.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The most recent day-ahead clear for the chosen region and block, in the native unit, with the timestamp and source.',
        agent_slug: 'contractiq_power_fairvalue',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'Real fetch. ERCOT and PJM clears are pulled from the futures proxy on Yahoo. European clears track the EEX and Nord Pool front-month futures. If the fetch failed, "data unavailable" is shown.',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'Forward fan from front-month through cal+2 in the region\'s native unit. Median anchored to the spot, band simulated from recent realised volatility.',
        agent_slug: 'contractiq_power_fairvalue',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'Anchor real, band simulated. Power vol is much higher than gas vol — the band on a Texan summer cal+1 will look wide compared to the equivalent TTF tenor, and that is correct.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'Current power-market headlines for the chosen region (renewable build, transmission outages, fuel-stack changes, demand response auctions). Sourced from web search.',
        agent_slug: 'contractiq_power_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Real headlines. Empty if search returned nothing.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'Short writeup of curve shape plus the provenance strip.',
        agent_slug: 'contractiq_power_fairvalue',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Prose grounded in the curve. Reference numbers in the writeup come from the structured agent output.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity=power and region',
        detail:
          'URL becomes /commodities/forward?commodity=power&region=de.',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'Single GET with the user token.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'The API calls contractiq_power_fairvalue with the region slug.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance, realized_vol_calc, monte_carlo_curve, tavily_search',
        detail:
          'Yahoo for the day-ahead anchor. Realised-vol calc on recent prints. Monte Carlo to fan out the curve. Tavily for current driver headlines on that grid.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'P50 front-month is snapped back to the real fetched clear if the agent drifted.',
      },
      {
        step: 6,
        label: 'UI renders curve + drivers + provenance',
        detail:
          'Native unit is applied per region — EUR/MWh in Europe, USD/MWh in the US.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_anchor', 'epex', 'nord_pool', 'ercot', 'pjm', 'capacity_factor', 'monte_carlo', 'contango', 'backwardation', 'p10_p50_p90', 'hub_vs_node']),
      {
        term: 'Base vs peak block',
        definition:
          'Base load is the average price across all hours of the day, 24/7. Peak is the average across the peak block (typically 8am to 8pm Mon-Fri). Peak trades a premium to base in summer-peaking grids and a smaller premium in winter-peaking ones.',
      },
    ],
  },

  'commodities-forward-carbon': {
    routeKey: 'commodities-forward-carbon',
    page_title: 'Forward fair-value · Carbon (EUA)',
    purpose:
      'This page builds a forward fair-value curve for EU emissions allowances. The EUA (European Union Allowance) is one permit to emit one tonne of CO2 inside the EU Emissions Trading Scheme. Prices are quoted in EUR per tonne of CO2. EUAs are the largest compliance carbon market in the world and the dominant price signal for European industrial emitters.\n\nThe EUA price is structurally supported by the Market Stability Reserve, which withdraws allowances from auction when the market surplus is too large. Demand is driven by the EU power sector\'s fuel-switching economics (coal vs gas at the marginal plant) and by industrial output. A forward curve on EUA reads like an expectation of where the cap-and-trade balance is going.\n\nThe spot anchor is a live fetch from the front-month EUA futures contract. The fan around it is a Monte Carlo calibrated to recent realised volatility. The guardrail re-anchors the median to the spot if the agent drifted. Provenance is on every render.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'Confirms commodity=carbon and product=EUA. URL becomes ?commodity=carbon. UKA (UK Allowance) and CCA (California) are not wired in this build.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'EUA only. The other compliance markets are noted in the selector but disabled.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'Fires the agent run. Debounced.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No execution until pressed.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The current EUA front-month print in EUR per tonne CO2, the refresh timestamp, and the data source.',
        agent_slug: 'contractiq_carbon_fairvalue',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'Real fetch via the EUA futures proxy on Yahoo. If the fetch failed the card shows "data unavailable" and the rest of the page degrades.',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'Forward fan from front-month through Dec+2 EUA contracts. Median anchored to spot, band simulated.',
        agent_slug: 'contractiq_carbon_fairvalue',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'Anchor real, band agent-simulated via Monte Carlo. EUA tends to trade in a more bounded range than gas or power but the band is still meaningful, especially across regulatory headline windows.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'Current EUA headlines (Commission auction calendar, MSR adjustments, fuel-switch coal-to-gas economics, industrial output prints, CBAM linkages).',
        agent_slug: 'contractiq_carbon_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Real web search results. Empty if search returned nothing.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'Short prose summary plus the provenance strip naming spot source and model.',
        agent_slug: 'contractiq_carbon_fairvalue',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Grounded in the structured outputs. Reference numbers come from the agent, not the model\'s prose.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity=carbon',
        detail:
          'URL becomes /commodities/forward?commodity=carbon.',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'Single GET with the user token.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'The API calls contractiq_carbon_fairvalue.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance, realized_vol_calc, monte_carlo_curve, tavily_search',
        detail:
          'Yahoo for EUA spot. Realised-vol calc on recent prints. Monte Carlo for the fan. Tavily for drivers.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'P50 front-month snapped to the real fetched spot.',
      },
      {
        step: 6,
        label: 'UI renders curve + drivers + provenance',
        detail:
          'Native unit is EUR per tonne CO2 across the chart.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_anchor', 'eua', 'ets', 'msr', 'monte_carlo', 'contango', 'backwardation', 'p10_p50_p90']),
      {
        term: 'CBAM',
        definition:
          'Carbon Border Adjustment Mechanism. The EU import duty on the embedded carbon content of cement, iron and steel, aluminium, fertilisers, electricity and hydrogen. Linked to the EUA price and a structural new source of demand for allowances over time.',
      },
      {
        term: 'Fuel switching',
        definition:
          'The choice at the marginal European power plant between burning coal and burning gas. The switching price is the EUA level at which gas becomes cheaper than coal once the carbon cost is included. It is the single most-watched lever in EUA fair-value modelling.',
      },
    ],
  },

  'commodities-forward-crude': {
    routeKey: 'commodities-forward-crude',
    page_title: 'Forward fair-value · Crude (Brent / WTI)',
    purpose:
      'This page builds a forward fair-value curve for crude oil. Pick the benchmark — Brent (the North Sea waterborne grade, the global crude reference, USD per barrel) or WTI (West Texas Intermediate, the US inland benchmark delivered at Cushing Oklahoma, also USD per barrel). The Brent-WTI spread itself is a tradeable arb that widens when US shale supply grows and narrows when pipeline takeaway from Cushing tightens.\n\nA crude forward curve is shaped by OPEC+ supply policy on the front and by long-cycle capex on the back. Contango (front cheaper than back) usually signals current oversupply. Backwardation (front more expensive than back) usually signals scarcity or strong demand. Geopolitical events — sanctions, war risk, freight disruption — pop the front of the curve hardest.\n\nThe spot anchor is the live front-month futures print. The fan around it is a Monte Carlo from recent realised vol. The guardrail re-anchors the P50 to the spot. Provenance is printed under every chart.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'Dropdown to pick benchmark (BRENT | WTI). URL becomes ?commodity=crude&benchmark=brent.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The benchmark choice is binary on this page — pick the one your physical is priced against.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'Fires the GET. Debounced.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No execution until pressed.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The front-month Brent or WTI futures print in USD per barrel, with the timestamp and source.',
        agent_slug: 'contractiq_crude_fairvalue',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'Real fetch from Yahoo. If the fetch failed the card shows "data unavailable".',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'Forward fan from front-month through cal+2. Median anchored to spot, band simulated.',
        agent_slug: 'contractiq_crude_fairvalue',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'Anchor real, band agent-simulated. Crude vol expands sharply around OPEC meeting weeks and Middle East tension headlines.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'Current crude headlines (OPEC+ quota decisions, US inventory builds, sanctions enforcement, refinery turnarounds, shipping disruption).',
        agent_slug: 'contractiq_crude_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Real web search hits. Empty if nothing came back.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'Short prose writeup plus the provenance strip.',
        agent_slug: 'contractiq_crude_fairvalue',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Reference numbers are from the structured outputs above.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity=crude and benchmark',
        detail:
          'URL becomes /commodities/forward?commodity=crude&benchmark=brent (or wti).',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'Single GET with the user token.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'API calls contractiq_crude_fairvalue with the benchmark slug.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance, realized_vol_calc, monte_carlo_curve, tavily_search',
        detail:
          'Yahoo for spot. Realised-vol calc. Monte Carlo for the fan. Tavily for drivers.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'Median front-month is snapped back to the real fetched spot if the agent drifted.',
      },
      {
        step: 6,
        label: 'UI renders curve + drivers + provenance',
        detail:
          'Native unit is USD per barrel across the chart.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_anchor', 'brent', 'wti', 'opec_quota', 'monte_carlo', 'contango', 'backwardation', 'basis_vs_benchmark', 'p10_p50_p90']),
      {
        term: 'Brent-WTI spread',
        definition:
          'The price gap between waterborne Brent and inland WTI. Widens when US shale production overwhelms Cushing pipeline takeaway. Narrows when Brent supply tightens or US exports rise. A real tradeable arb on the global crude complex.',
      },
    ],
  },

  'commodities-forward-refined': {
    routeKey: 'commodities-forward-refined',
    page_title: 'Forward fair-value · Refined products (RBOB / ULSD / Jet)',
    purpose:
      'This page builds a forward fair-value curve for refined products. Pick the product — RBOB (the NYMEX gasoline contract, USD per gallon), ULSD (Ultra-Low Sulphur Diesel, the NYMEX heating-oil and diesel contract, USD per gallon) or JET (jet fuel, USD per gallon, often quoted on the ICE Gasoil contract as a proxy with a basis adjustment).\n\nRefined-product curves are driven by the crack spread (the refiner margin = product price minus crude cost) and by refinery utilization. When utilization runs hot above 92%, cracks blow out on any unplanned outage. When cracks are wide, refiners run harder, which eventually loosens product. Seasonality matters — RBOB peaks into US summer driving, ULSD peaks into Northeast winter heating, jet rises into peak air-travel windows.\n\nThe spot anchor is the front-month product futures print. The fan is a calibrated Monte Carlo. The guardrail re-anchors the median to the spot. Provenance is printed under every chart.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'Dropdown to pick product (RBOB | ULSD | JET). URL becomes ?commodity=refined&product=rbob.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Pick the product that matches what you are physically buying or selling. Cracks differ by product even on the same crude run.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'Fires the GET. Debounced.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No execution until pressed.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The current front-month product futures print in USD per gallon, with the timestamp and source.',
        agent_slug: 'contractiq_refined_fairvalue',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'Real fetch via Yahoo. For JET the page uses ICE Gasoil as a proxy with a documented basis adjustment.',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'Forward fan from front-month through cal+1. Median anchored to spot, band simulated.',
        agent_slug: 'contractiq_refined_fairvalue',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'Anchor real, band agent-simulated. Refined-product vol is dominated by refinery outage risk and seasonal demand swings — the band widens visibly into summer for RBOB and into winter for ULSD.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'Current refined-product headlines (refinery turnarounds, EIA weekly inventory builds, US driving season demand, hurricane risk on Gulf Coast refining).',
        agent_slug: 'contractiq_refined_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Real web search hits. Empty if nothing came back.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'Short prose writeup plus the provenance strip naming the spot source and the model.',
        agent_slug: 'contractiq_refined_fairvalue',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Reference numbers in the writeup come from the structured outputs.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity=refined and product',
        detail:
          'URL becomes /commodities/forward?commodity=refined&product=rbob (or ulsd, jet).',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'Single GET with the user token.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'API calls contractiq_refined_fairvalue with the product slug.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance, realized_vol_calc, monte_carlo_curve, tavily_search',
        detail:
          'Yahoo for spot. Realised-vol calc on the recent print history. Monte Carlo for the fan. Tavily for drivers.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'Median front-month snapped to the real fetched spot.',
      },
      {
        step: 6,
        label: 'UI renders curve + drivers + provenance',
        detail:
          'Native unit USD per gallon across the chart.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_anchor', 'rbob', 'ulsd', 'crack_spread', 'refinery_utilization', 'monte_carlo', 'contango', 'backwardation', 'seasonality', 'p10_p50_p90']),
      {
        term: 'Jet fuel basis',
        definition:
          'The price gap between jet fuel and the nearest liquid futures contract (typically ICE Gasoil or NYMEX ULSD). Jet is not deeply futures-traded so most curves rebuild it with a basis to a more liquid distillate.',
      },
    ],
  },

  'commodities-forward-coal': {
    routeKey: 'commodities-forward-coal',
    page_title: 'Forward fair-value · Thermal coal (Newcastle / API2 / API4)',
    purpose:
      'This page builds a forward fair-value curve for thermal coal. Pick the index — NEWCASTLE (the Pacific-basin benchmark, FOB Newcastle Australia, USD per tonne, 6000 kcal/kg), API2 (the Atlantic-basin benchmark, CIF Amsterdam-Rotterdam-Antwerp, USD per tonne) or API4 (FOB Richards Bay South Africa, USD per tonne). The basis between Newcastle and API2 tracks Atlantic-Pacific tightness — when one basin runs short of coal, cargoes are pulled across and the spread compresses.\n\nA coal forward curve is driven by Chinese, Indian and Japanese utility demand (Pacific basin) and European utility demand plus EU power coal-burn economics (Atlantic basin). The structural backdrop is declining — European demand is shrinking as the EUA price keeps gas competitive — but Asian demand and weather-driven spikes can still pull big moves. Coal vol can be very episodic.\n\nThe spot anchor is the front-month index print. The fan is a Monte Carlo from realised vol. The guardrail re-anchors the P50 to the spot. Provenance on every render.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'Dropdown to pick index (NEWCASTLE | API2 | API4). URL becomes ?commodity=coal&index=newcastle.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Pick the index that matches your physical supply contract.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'Fires the GET. Debounced.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No execution until pressed.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The current front-month index print in USD per tonne, with the timestamp and source.',
        agent_slug: 'contractiq_coal_fairvalue',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'Real fetch via Yahoo (thermal coal futures proxy). If the fetch failed the card prints "data unavailable".',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'Forward fan from front-month through cal+1. Median anchored to spot, band simulated.',
        agent_slug: 'contractiq_coal_fairvalue',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'Anchor real, band simulated. Coal vol is episodic — long quiet stretches punctuated by sharp spikes when Asian winter weather or European gas substitution kicks in. The band widens through winter tenors.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'Current coal headlines (Chinese restocking, Indian utility purchases, Australian export weather, South African rail capacity, European coal-burn economics).',
        agent_slug: 'contractiq_coal_fairvalue',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Real web search hits. Empty if nothing came back.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'Short prose writeup plus the provenance strip.',
        agent_slug: 'contractiq_coal_fairvalue',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'Reference numbers come from the structured outputs.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity=coal and index',
        detail:
          'URL becomes /commodities/forward?commodity=coal&index=newcastle (or api2, api4).',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/commodities/{slug}/forward/run',
        detail:
          'Single GET with the user token.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'API calls contractiq_coal_fairvalue with the index slug.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance, realized_vol_calc, monte_carlo_curve, tavily_search',
        detail:
          'Yahoo for spot. Realised-vol calc on recent prints. Monte Carlo for the fan. Tavily for drivers.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'Median front-month snapped to the real fetched spot if the agent drifted.',
      },
      {
        step: 6,
        label: 'UI renders curve + drivers + provenance',
        detail:
          'Native unit USD per tonne across the chart.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_anchor', 'newcastle_thermal', 'api2_api4', 'monte_carlo', 'contango', 'backwardation', 'basis_vs_benchmark', 'p10_p50_p90']),
      {
        term: 'Atlantic-Pacific basin arb',
        definition:
          'The trade that opens when API2 (Atlantic, Amsterdam delivered) and Newcastle (Pacific, Australia loaded) prices diverge enough to make cross-basin shipping economic. The arb closes when cargoes get redirected and the spread compresses.',
      },
      {
        term: '6000 kcal/kg specification',
        definition:
          'The energy content standard that Newcastle, API2 and API4 all reference. Coal with different calorific value trades at a documented heat-adjusted basis to the benchmark.',
      },
    ],
  },

  'price-engine': {
    routeKey: 'price-engine',
    page_title: 'Dynamic Forward Price Engine',
    purpose:
      'This page is the cross-commodity price engine. One screen to query a forward fair value for any of the commodities the platform covers — gas, LNG, power (across five regions), carbon, crude, refined products, coal — and a single consistent output shape: spot anchor, P10/P50/P90 fan, drivers, summary, provenance. It is the lowest-friction way to pull a fair value when you do not need the full commodity-specific page.\n\nThe engine fans out to the per-commodity agents under the hood. It is a router, not a separate computation. So the numbers you get here match exactly what you would see on the dedicated /commodities/forward?commodity=X page for the same selection. The point of this page is the consolidated input form — pick commodity, region/benchmark, tenor — and the consolidated output card.\n\nEvery answer carries the same provenance commitments as the dedicated pages. Anchor is a real fetch. Band is an agent-simulated Monte Carlo. Drivers are real web search results. The canonical-anchor guardrail keeps the median honest. If a commodity feed fails the page returns "data unavailable" rather than a fabricated number.',
    sections: [
      {
        title: 'Commodity / region / product selector',
        what_it_shows:
          'A unified picker — commodity (gas, lng, power, carbon, crude, refined, coal), region/benchmark for the ones that have it, tenor span (front-month through cal+2). The picker validates that the combination is wired.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'If a combination is not yet wired (e.g. UKA carbon, RTO power for a region the engine has not yet seeded), the selector greys it out.',
      },
      {
        title: 'Run analysis CTA',
        what_it_shows:
          'Single button to fire the GET /api/contractiq/price-engine/run call. Debounced. Loading skeletons on the chart and the cards while the agent runs.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No agent runs until pressed.',
      },
      {
        title: 'Spot anchor card',
        what_it_shows:
          'The live front-month print for the selected commodity in its native unit, with refresh timestamp and source. Same data point as the dedicated /commodities/forward page would show.',
        agent_slug: 'ciq-price-engine',
        tools_used: ['yahoo_finance'],
        data_quality: 'real-fetched',
        layman_note:
          'Real fetch from Yahoo. If the source did not respond the card shows "data unavailable" rather than synthesising a number.',
      },
      {
        title: 'Fan chart (P10 / P50 / P90)',
        what_it_shows:
          'Forward fan in the native unit. Median anchored to the spot, band simulated by Monte Carlo over recent realised volatility.',
        agent_slug: 'ciq-price-engine',
        tools_used: ['yahoo_finance', 'realized_vol_calc', 'monte_carlo_curve'],
        data_quality: 'mixed',
        layman_note:
          'The engine routes to the per-commodity agent — for power that means contractiq_power_fairvalue, for gas contractiq_pipeline_gas_fairvalue and so on. Same numbers as the dedicated page.',
      },
      {
        title: 'Drivers panel',
        what_it_shows:
          'Current driver headlines for the selected commodity, pulled by web search at the time of the run.',
        agent_slug: 'ciq-price-engine',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Real search hits. Empty if search returned nothing.',
      },
      {
        title: 'Summary markdown and provenance banner',
        what_it_shows:
          'A short LLM-written summary of the curve plus the provenance strip naming the spot source, the model behind the band, and a corrected flag if the canonical-anchor guardrail had to snap the median back to the fetched anchor.',
        agent_slug: 'ciq-price-engine',
        tools_used: [],
        data_quality: 'mixed',
        layman_note:
          'The summary prose is the agent\'s own LLM output (not a separate tool). Read the banner before quoting a number. Same colour-coding as the dedicated pages — green for fully live, amber for fully simulated, blue for mixed.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'User selects commodity, region/benchmark, tenor',
        detail:
          'The unified picker composes the request payload. URL is /price-engine.',
      },
      {
        step: 2,
        label: 'GET /api/contractiq/price-engine/run',
        detail:
          'Browser sends the request with the user token. No streaming.',
      },
      {
        step: 3,
        label: 'AgentForge agent run via SDK',
        detail:
          'The API routes to the right per-commodity agent (contractiq_pipeline_gas_fairvalue, contractiq_lng_fairvalue, contractiq_power_fairvalue, contractiq_carbon_fairvalue, contractiq_crude_fairvalue, contractiq_refined_fairvalue, contractiq_coal_fairvalue) based on the commodity slug.',
      },
      {
        step: 4,
        label: 'Agent calls yahoo_finance / realized_vol_calc / monte_carlo_curve / tavily_search',
        detail:
          'Same tool chain as the dedicated page. Spot anchor real, vol calibration from recent prints, Monte Carlo for the band, web search for drivers.',
      },
      {
        step: 5,
        label: 'Deterministic canonical-anchor guardrail validates the band',
        detail:
          'P50 front-month is checked against the real fetched anchor. If the agent drifted, the median is snapped back and the corrected flag is set on the provenance banner.',
      },
      {
        step: 6,
        label: 'UI renders curve + drivers + provenance',
        detail:
          'Same render components as the dedicated /commodities/forward page. Same numbers, same provenance commitments.',
      },
    ],
    glossary: [
      ...pick(['forward_curve', 'fair_value', 'spot_price', 'spot_anchor', 'monte_carlo', 'contango', 'backwardation', 'basis_risk', 'p10_p50_p90', 'guardrail', 'agent', 'pipeline']),
      {
        term: 'Router pattern',
        definition:
          'A thin endpoint that does not compute the answer itself — it picks the right specialist agent and delegates. The price engine is a router. The math lives in the per-commodity agents it calls.',
      },
    ],
  },

  'credit-risk-kyc-new': {
    routeKey: 'credit-risk-kyc-new',
    page_title: 'New KYC Standard Check',
    purpose:
      'This page starts a new KYC run on a counterparty before you open or expand a trading relationship with them. You fill in the legal entity, the commercial context (annual notional, currency, industry segment, business relationship type) and a brief compliance posture (any prior sanctions touch, whether the counterparty already exists in your book). The page then kicks off an agent that runs the standard MET-style template — a tri-indicator score, an intermediate compliance checklist and a recommended four-state outcome.\n\nThe MET template is the same shape every time so the report reads cleanly to a local KYC analyst, a regional compliance officer and group compliance. The tri-indicator score is built from three sub-scores (Country CPI rank, annual notional band, industry segment risk) where each input is a real fetch and the composite ranking is judged by the LLM. The intermediate checklist is ten Wolfsberg-aligned rows graded L/M/H by the LLM against the contract context and the agent search hits. The four-state outcome is the agent recommendation (positive, positive with conditions, negative, pending) and is also LLM-judged.\n\nThe sign-off line is the most important part of this template and it never sits with the agent. The agent produces a recommendation and the evidence behind it. A human KYC owner accepts the recommendation, accepts with conditions, or overrides it. The audit trail captures who signed off and when so the file is defensible against a later regulator review.',
    sections: [
      {
        title: 'Counterparty identity card',
        what_it_shows:
          'Legal entity name, country of incorporation, registration number where known, parent group, and ultimate beneficial owner field. A confidence pill shows how sure the agent is that it has the right entity, not how trustworthy the entity is.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['tavily_search'],
        data_quality: 'real-fetched',
        layman_note:
          'Entity resolution is one step inside the kyc-standard-check agent — it runs a tavily_search over the legal name + country to confirm the match before the rest of the run consumes the result. If two companies share a name, low confidence means the rest of the run may end up describing the wrong one. Always check the country and address before kicking off the run.',
      },
      {
        title: 'Risk Indicators',
        what_it_shows:
          'Annual notional in the trading currency, currency itself, industry segment (mapped to a NACE code), business relationship type (counterparty, supplier, client, intermediary), and proposed trading limits.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'These are the values you typed. They drive the Notional sub-score and the Industry sub-score in the tri-indicator. A wrong industry pick here will skew the whole rating.',
      },
      {
        title: 'Administrative (optional)',
        what_it_shows:
          'Sanctions pre-screen banner driven by an OFAC / EU / UN / UK list query for the entity name. Counterparty dedup check against the existing book — if a record already exists, the banner flags it so you do not open a duplicate file.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['tavily_search', 'database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The sanctions pre-screen is a tavily_search keyed on phrases like "<entity> OFAC SDN", "<entity> EU consolidated sanctions list" and "<entity> UK OFSI sanctions". A pre-screen hit is a hard stop and the Run KYC button is disabled until the case is escalated. A miss does not certify the entity as clean — the full run still re-screens against the same sources with broader matching rules.',
      },
      {
        title: 'Run KYC button',
        what_it_shows:
          'Submits the form and kicks off the kyc-standard-check agent. Loading skeleton appears on the next page while the agent works through its tool chain.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['country_cpi_lookup', 'industry_segment_risk', 'moodys_orbis_lookup', 'tavily_search'],
        data_quality: 'mixed',
        layman_note:
          'country_cpi_lookup is a real fetch against the Transparency International CPI snapshot. industry_segment_risk maps the NACE code to a baseline risk band from a local table. moodys_orbis_lookup is wired but the credential is not provisioned in this deployment — the tool returns an explicit unavailable banner rather than a fabricated answer. tavily_search pulls recent adverse media.',
      },
      {
        title: 'PDF import zone',
        what_it_shows:
          'Drag-and-drop area for supporting documents (incorporation certificate, board resolutions, KYC questionnaires returned by the counterparty). Kicks off the contractiq-kyc-pdf-intake pipeline.',
        agent_slug: 'contractiq-kyc-pdf-intake',
        tools_used: ['kyc_met_pdf_extractor'],
        data_quality: 'mixed',
        layman_note:
          'The vision LLM reads each page and returns extracted fields as {value, confidence, raw_snippet} envelopes. Low-confidence fields are highlighted on the next page so a human reviewer can correct them before the run lands in the audit trail.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'You submit the form on /credit-risk/kyc/new',
        detail:
          'Browser posts the form payload (entity, commercial context, posture) to /api/contractiq/insights/kyc with the user token in the Authorization header.',
      },
      {
        step: 2,
        label: 'API persists a pending KYC row and forwards to AgentForge',
        detail:
          'A KYC row is written in pending state so the audit trail starts immediately. The API then calls the kyc-standard-check agent through the SDK with the form payload as input.',
      },
      {
        step: 3,
        label: 'Agent calls its tools',
        detail:
          'country_cpi_lookup for the Country sub-score, industry_segment_risk for the Industry sub-score, moodys_orbis_lookup for entity background (returns unavailable banner in this deployment), and tavily_search for adverse media and PEP context.',
      },
      {
        step: 4,
        label: 'Agent assembles the MET-style report',
        detail:
          'The agent fills the tri-indicator score, the ten-row intermediate compliance checklist and the four-state outcome with reasoning, then returns the structured report to the API.',
      },
      {
        step: 5,
        label: 'API updates the row, browser routes to the detail page',
        detail:
          'The pending row is updated with the agent recommendation in awaiting_sign_off state. The browser redirects to /credit-risk/kyc/[id] where the human sign-off gate sits.',
      },
      {
        step: 6,
        label: 'Human sign-off gate',
        detail:
          'The agent recommendation is not the final answer. A human KYC owner accepts, accepts with conditions, or overrides. The agent never signs off.',
      },
    ],
    glossary: [
      ...pick(['kyc', 'counterparty', 'agent', 'pipeline', 'cpi_rank', 'transparency_international', 'nace', 'fatf', 'sanctions_screening', 'pep', 'ubo', 'moodys_orbis', 'met_template', 'tri_indicator', 'wolfsberg', 'isda']),
      {
        term: 'Four-state outcome',
        definition:
          'The recommended verdict slot in the MET template. positive means accept as proposed. positive_with_conditions means accept subject to named mitigations (extra collateral, smaller limit, refresh in 6 months). negative means do not onboard. pending means the agent could not gather enough evidence and a human reviewer must take it forward.',
      },
      {
        term: 'Sign-off (human-only)',
        definition:
          'The act of a named human KYC owner accepting, conditionally accepting, or overriding the agent recommendation. The agent never signs off. The sign-off identity, time and reasoning are stored in the audit trail so the file is defensible to a regulator.',
      },
    ],
  },

  'credit-risk-kyc-detail': {
    routeKey: 'credit-risk-kyc-detail',
    page_title: 'KYC Standard Check Detail',
    purpose:
      'This page shows the result of a single KYC run and is where the human sign-off happens. The MET-style template is rendered top to bottom — the tri-indicator score with its three sub-scores, the ten-row intermediate compliance checklist, the four-state outcome pill with the agent reasoning, the per-role sign-off lane, and the audit trail with the next review date.\n\nEvery number on this page traces back to a tool call or a human action and is labelled accordingly. The Country, Notional and Industry sub-scores under the tri-indicator come from real fetches. The composite tri-indicator number and the checklist row grades are LLM-judged ranks, marked data_quality mixed. The four-state outcome is the agent recommendation. The sign-off lane is the only place a human writes onto the record, and that write becomes the final authority — the agent recommendation stays visible as evidence but does not bind the file.\n\nIf the agent honestly could not assemble enough evidence (Orbis unavailable, no adverse media hits, no sanctions context), the outcome stays pending and the page tells you which row in the checklist is responsible. The reviewer can either request an information re-fetch or escalate. Nothing on this page is auto-resolved by the agent after the initial run.',
    sections: [
      {
        title: 'Tri-indicator score panel',
        what_it_shows:
          'A 15-75 composite number with three sub-scores below it: Country (CPI rank), Annual Notional (band), Industry Segment (NACE-mapped risk). Each sub-score is a 5-25 input.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['country_cpi_lookup', 'industry_segment_risk'],
        data_quality: 'mixed',
        layman_note:
          'The three inputs are real-fetched but the composite ranking and the tier selection (Simplified, Standard, Enhanced, Special) are an LLM-judged opinion. Two runs on the same inputs can pick different tiers in edge cases.',
      },
      {
        title: 'Intermediate compliance checklist',
        what_it_shows:
          'Ten rows aligned to Wolfsberg control areas (entity verification, UBO identification, sanctions screening, PEP screening, source of funds, adverse media, business rationale, expected activity profile, regulatory licences, ISDA master agreement coverage). Each row carries an L/M/H risk grade and a citation.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['tavily_search'],
        data_quality: 'mixed',
        layman_note:
          'Each grade is an LLM judgement against the row description, the contract context and the search hits. The citation under each row should be read before treating the grade as final. Missing citations are a sign the grade is weak.',
      },
      {
        title: 'Four-state outcome pill',
        what_it_shows:
          'One of positive, positive_with_conditions, negative or pending. Below the pill the agent narrates which checklist rows drove the verdict and which sub-scores moved it.',
        agent_slug: 'kyc-standard-check',
        tools_used: ['llm_call'],
        data_quality: 'mixed',
        layman_note:
          'This is the agent recommendation, not the final answer. The sign-off lane below can accept it, accept with conditions, or override it.',
      },
      {
        title: 'Per-role sign-off (human action only)',
        what_it_shows:
          'One row per required sign-off role (local KYC analyst, regional compliance, group compliance). Each row has an accept, accept with conditions and override action, a free-text reasoning box, and a timestamp.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The agent never writes here. Every action is a human keystroke. The reasoning text is persisted verbatim into the audit trail so it can be replayed in a regulator review.',
      },
      {
        title: 'Next review due',
        what_it_shows:
          'A date computed from the sign-off and the tier — Simplified refreshes every 36 months, Standard every 24, Enhanced every 12, Special every 6. The date is set when the final sign-off lands.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Arithmetic on the sign-off date and the tier. Not a model output. The calendar reminder is fired from this field.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser loads /credit-risk/kyc/[id]',
        detail:
          'GET to /api/contractiq/insights/kyc/{id}. The API returns the persisted row including the agent recommendation, the tri-indicator, the checklist and the audit trail.',
      },
      {
        step: 2,
        label: 'UI renders the MET template panels',
        detail:
          'No further agent run on load. Everything shown is what the kyc-standard-check agent wrote at the end of the new-KYC flow plus any subsequent human sign-off actions.',
      },
      {
        step: 3,
        label: 'Reviewer clicks accept / accept_with_conditions / override',
        detail:
          'POST to /api/contractiq/insights/kyc/{id}/sign-off with the role, the action, the free-text reasoning and any condition list. The API writes an audit row and updates the state.',
      },
      {
        step: 4,
        label: 'API recomputes the next review due date',
        detail:
          'When the last required role signs off, the API sets next_review_due based on the final tier. The row moves to closed_signed_off state.',
      },
      {
        step: 5,
        label: 'Sign-off gate is human-only',
        detail:
          'No agent path can land a sign-off action. The kyc-standard-check agent can be re-run on the same case to refresh the recommendation, but it cannot close the file.',
      },
    ],
    glossary: [
      ...pick(['kyc', 'counterparty', 'agent', 'mtm', 'cpi_rank', 'transparency_international', 'nace', 'fatf', 'wolfsberg', 'sanctions_screening', 'pep', 'risk_tier', 'pd', 'isda', 'met_template', 'tri_indicator']),
      {
        term: 'Intermediate compliance checklist',
        definition:
          'The ten-row Wolfsberg-aligned grid that sits between the tri-indicator score and the four-state outcome in the MET template. Each row carries an L/M/H grade. The checklist is LLM-judged from the contract context and the search hits, with citations under each row.',
      },
      {
        term: 'Four-state outcome',
        definition:
          'The recommended verdict slot in the MET template. positive means accept as proposed. positive_with_conditions means accept subject to named mitigations. negative means do not onboard. pending means the agent could not assemble enough evidence and a human reviewer must take it forward.',
      },
      {
        term: 'Sign-off (human-only)',
        definition:
          'The act of a named human KYC owner accepting, conditionally accepting, or overriding the agent recommendation. The agent never signs off. The sign-off identity, time and reasoning are stored in the audit trail so the file is defensible to a regulator.',
      },
    ],
  },

  chat: {
    routeKey: 'chat',
    page_title: 'Cross-Contract Intelligence (chat)',
    purpose:
      'This is the chat workspace for asking plain-English questions across every contract you have uploaded. The agent on the other end is the contractiq-chat agent — a Gemini-backed assistant that receives, on every turn, a fresh portfolio brief listing each contract you own with its title, type, counterparties, capacity, value, currency, effective and expiry dates and risk score. That brief is the source of truth. The agent computes aggregates and answers directly from it, and only calls tools when the question asks for something the brief does not contain.\n\nConversations are saved as threads in the left sidebar. Each thread is bound to your acting subject and to the contractiq app slug, so it survives sign-outs and shows up the next time you open the page. The brief travels per turn as fresh context rather than as part of the persisted history, so the thread record stays small and your own words are the only thing stored there. The agent is configured with cache disabled because two questions that look similar in text (count my contracts vs how many contracts do I have) may need fresh database state to answer correctly.\n\nA realistic note. The answer is markdown text written by an LLM. Numbers cited back to you came either from the portfolio brief (real DB rows) or from a tool the agent called. Aggregate maths happens inside the model, not in a verified computation step. Spot-check totals on the [My Contracts](/contracts) list when something looks off.',
    sections: [
      {
        title: 'Thread sidebar (New chat, list, delete)',
        what_it_shows:
          'The persistent list of saved chat threads for your account. The New chat button starts a fresh thread, clicking a thread loads its full message history, and the trash icon deletes the thread on the agent runtime side.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The sidebar is a thin client over the agent-runtime chat store. No LLM runs to populate it. Threads here are real rows owned by your acting subject, not synthesised.',
      },
      {
        title: 'Suggestions grid (empty state)',
        what_it_shows:
          'Six starter prompts that appear before any message is sent: curtailment protection, pricing and escalation, MW exposure expiring before 2030, force majeure coverage, summary of key risks, payment and settlement terms.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Static prompts authored by the team. Clicking one sends it as the first user message of a new thread, nothing more.',
      },
      {
        title: 'Conversation messages',
        what_it_shows:
          'The chat transcript. User turns appear right-aligned, assistant turns left-aligned with the E&C-Copilot label, the contract count analysed and the clause count searched. Markdown is rendered inline (headers, bullets, tables, bold, italics, code).',
        agent_slug: 'contractiq-chat',
        tools_used: ['knowledge_search', 'financial_calculator', 'entso_e_tool', 'ember_tool', 'ecb_rates_tool', 'graph_explorer_tool'],
        data_quality: 'mixed',
        layman_note:
          'The portfolio brief is real data. The narrative around it is the LLM compressing that brief plus any tool results into prose. Treat numbers cited as the answer to your question as model output, not as a verified report.',
      },
      {
        title: 'Source pills (per assistant turn)',
        what_it_shows:
          'A row of small chips at the bottom of an assistant message, one per contract the agent considered, each linking to the contract detail page and coloured by contract type (PPA, gas, other).',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The sources list is your own contracts table at the moment the question was asked, not a model-generated bibliography. Clicking a pill opens the actual contract detail page.',
      },
      {
        title: 'Composer (input + send)',
        what_it_shows:
          'The text input at the bottom and the send button. Enter sends, the button shows a spinner while the agent is running.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'No agent at this step until you press send. The spinner indicates the agent runtime is processing your turn.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GET /api/contractiq/chat/threads',
        detail:
          'On page load, the sidebar pulls the most recent 50 threads for your user via the agent-runtime chat list endpoint. No model is invoked.',
      },
      {
        step: 2,
        label: 'Browser GET /api/contractiq/chat/threads/{id} when you click a thread',
        detail:
          'Returns the full message history for that thread. The UI maps each persisted message to a Message object and renders the transcript.',
      },
      {
        step: 3,
        label: 'Browser POST /api/contractiq/chat with query and optional thread_id',
        detail:
          'The ContractIQ API validates the query length, counts your contracts, builds a portfolio brief from the contracts table, and either reuses the latest thread or creates a new one bound to app_slug contractiq and agent_slug contractiq-chat.',
      },
      {
        step: 4,
        label: 'API calls forge.chat.send with the brief as fresh context',
        detail:
          'The portfolio brief travels per turn as context rather than as part of the persisted message. The agent runtime repacks prior turns plus the new context and runs contractiq-chat (Gemini 2.0 Flash, 15 max iterations, cache disabled).',
      },
      {
        step: 5,
        label: 'Agent calls its tools as needed',
        detail:
          'Tools available to the agent are knowledge_search for clause text, financial_calculator for NPV/IRR/LCOE, entso_e / ember_climate / ecb_rates for live market and FX, graph_explorer for entity relationships. The brief itself handles count and aggregate questions without a tool call.',
      },
      {
        step: 6,
        label: 'API returns answer, sources, contracts_analyzed, model, cost',
        detail:
          'The browser appends the assistant turn to the transcript, captures meta about the run, and refreshes the sidebar so the new thread shows up.',
      },
      {
        step: 7,
        label: 'DELETE /api/contractiq/chat/threads/{id} when you trash a thread',
        detail:
          'Calls the agent runtime chat delete endpoint and reloads the sidebar. The transcript is removed from the store.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'mtm', 'ppa', 'agent', 'agentic_workflow', 'llm_cost']),
      {
        term: 'Portfolio brief',
        definition:
          'A compact text block built fresh on every chat turn that lists every contract you own with title, type, counterparties, capacity, value, currency, effective and expiry dates, and risk score. The agent treats this as the source of truth and answers count and aggregate questions directly from it, without a tool call.',
      },
      {
        term: 'Chat thread',
        definition:
          'A persisted conversation in the agent runtime chat store, bound to your acting subject and to the contractiq app slug. Survives sign-outs. The brief is sent per turn so only the user words and assistant replies are stored on the thread.',
      },
      {
        term: 'Acting subject',
        definition:
          'The ContractIQ end user identity that the API passes to AgentForge when calling the chat agent. Lets the agent runtime scope chat threads, audit and cost back to a real person rather than to the ContractIQ service account.',
      },
      {
        term: 'Tool call (chat)',
        definition:
          'When the agent runs a tool to fetch something the portfolio brief does not have. Examples: knowledge_search for clause text, financial_calculator for NPV maths, entso_e for European power prices, graph_explorer for cross-entity links.',
      },
    ],
  },

  'insights-renewals': {
    routeKey: 'insights-renewals',
    page_title: 'Renewal Negotiation Copilot',
    purpose:
      'This page assembles a complete renewal negotiation packet for any contract in your portfolio that is approaching expiry. The point is to give the human dealmaker everything they need to walk into the room confident: a snapshot of the upcoming renewal queue, a one-click packet build per contract, and a three-position term sheet (aggressive, middle, fallback) with NPV uplift estimates anchored to comparable contracts and live forward markets.\n\nThe upcoming-renewals card list is a straight database query against contracts with parsed expiry dates inside a 180-day window. It is not a model output. The packet itself is built by the contractiq-renewal-copilot agent, which loads the contract record, pulls comparable contracts from your portfolio, fetches current and forward levels for the underlying commodity from public sources, runs financial_calculator for NPV maths, and writes back a structured packet plus a full markdown narrative. The agent runs once per contract you click; subsequent reloads read the persisted packet without re-running.\n\nA realistic note. The NPV uplift figure on each negotiation position is a model-computed estimate, not a quote and not a guaranteed deal value. Counterparty intel is sourced from web search and may be stale by hours or days. Always read the citations in the full packet before taking a position to the counterparty.',
    sections: [
      {
        title: 'Upcoming Renewals (next 180 days)',
        what_it_shows:
          'One card per contract with an expiry date in the next 180 days. Each card lists contract type, title, counterparties, days-to-expiry pill (red under 30, amber under 90, emerald otherwise), capacity in MW, risk score and expiry date. The Build Negotiation Packet button triggers an agent run.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Pure database read of your contracts table filtered on expiry_date. If a contract is missing an expiry date it will not appear here even if it really is expiring. Fix the extracted field on the contract detail page to surface it.',
      },
      {
        title: 'Negotiation Positions (aggressive / middle / fallback)',
        what_it_shows:
          'A three-column card grid for the generated packet showing aggressive, middle and fallback term sheets. Each card lists the key terms the agent proposed (price, tenor, indexation, escalators) with the NPV impact and a probability-of-acceptance value.',
        agent_slug: 'contractiq-renewal-copilot',
        tools_used: ['database_query', 'entso_e_tool', 'ember_tool', 'ecb_rates_tool', 'financial_calculator'],
        data_quality: 'agent-simulated',
        layman_note:
          'These positions are the agent\'s recommendation, not a binding offer. NPV figures are model arithmetic across the proposed tenor at the current forward curve. Probability of acceptance is an LLM-judged estimate, not a calibrated forecast.',
      },
      {
        title: 'Market Context',
        what_it_shows:
          'A cyan-bordered card with a JSON pretty-print of the live and forward market levels the agent pulled for the underlying commodity: current vs forward power, gas or FX levels relevant to the contract.',
        agent_slug: 'contractiq-renewal-copilot',
        tools_used: ['entso_e_tool', 'ember_tool', 'ecb_rates_tool'],
        data_quality: 'real-fetched',
        layman_note:
          'These numbers come from the agent\'s tool calls into ENTSO-E, Ember Climate and ECB at the time the packet was built. Refresh by re-running Build Negotiation Packet — the page does not auto-refresh market levels.',
      },
      {
        title: 'Counterparty Intel',
        what_it_shows:
          'A purple-bordered card with the agent\'s notes on the counterparty: corporate news, credit signals, prior negotiation patterns. Displayed as a JSON pretty-print.',
        agent_slug: 'contractiq-renewal-copilot',
        tools_used: ['tavily_search', 'database_query'],
        data_quality: 'mixed',
        layman_note:
          'The web search hits are real at the moment of the run. The synthesis around them is LLM. Treat the bullets as starting points for diligence, not as verified intelligence.',
      },
      {
        title: 'Full Packet (markdown)',
        what_it_shows:
          'The complete narrative version of the packet rendered as markdown — executive summary, market context, historical pricing trend, comparable transactions, counterparty intel and the three positions with rationale. Sourced from the full_packet_markdown field returned by the agent.',
        agent_slug: 'contractiq-renewal-copilot',
        tools_used: ['database_query', 'entso_e_tool', 'ember_tool', 'ecb_rates_tool', 'financial_calculator', 'tavily_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'This is the agent talking, not a templated report. Read for the reasoning, then test the numbers against the structured fields above before lifting any of it into a real negotiation document.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GET /api/contractiq/insights/renewals/upcoming?days=180',
        detail:
          'The router queries the contracts table for rows owned by the user with expiry_date inside the next 180 days. Returns a list of UpcomingRenewal objects. No agent runs.',
      },
      {
        step: 2,
        label: 'Browser GET /api/contractiq/insights/renewals',
        detail:
          'Returns previously generated packets persisted in the contractiq_renewal_packets table. Each row contains structured fields plus the full markdown.',
      },
      {
        step: 3,
        label: 'User clicks Build Negotiation Packet',
        detail:
          'Browser POSTs to /api/contractiq/insights/renewals/{contract_id}/generate. The router builds a contract-specific message and calls _call_abenix(user, "contractiq-renewal-copilot", msg).',
      },
      {
        step: 4,
        label: 'Agent runs its tool plan',
        detail:
          'contractiq-renewal-copilot uses database_query to load the target contract and comparable contracts, entso_e / ember_climate / ecb_rates for the live and forward market context, tavily_search for counterparty news, and financial_calculator for NPV maths across the three proposed positions.',
      },
      {
        step: 5,
        label: 'Router persists the packet and returns it',
        detail:
          'The agent\'s structured JSON is saved into contractiq_renewal_packets with status completed. The browser reloads the packet list and the new entry appears at the top.',
      },
      {
        step: 6,
        label: 'UI renders the three-position grid, market and counterparty cards, then the full markdown',
        detail:
          'No further computation in the browser beyond formatting. The packet you see is exactly what the agent wrote on the original run.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'mtm', 'ppa', 'forward_curve', 'agent', 'agentic_workflow']),
      {
        term: 'NPV uplift',
        definition:
          'The difference in net present value between a proposed renewal position and a defined baseline (typically the rolled-over current terms). A positive uplift means the position is worth more than the baseline at the discount rate the agent used.',
      },
      {
        term: 'Three-position term sheet',
        definition:
          'The aggressive, middle and fallback bundle the agent proposes for the renewal. Each is a coherent set of price, tenor, indexation and escalator terms with its own NPV and probability of acceptance. Lets the dealmaker walk in with an opening ask, a likely landing zone, and a walk-away floor already drafted.',
      },
      {
        term: 'Probability of acceptance',
        definition:
          'The agent\'s LLM-judged estimate of how likely the counterparty is to accept a given position. It is opinion, not calibration. Use to rank positions, not as a hard forecast.',
      },
      {
        term: 'Comparable contracts',
        definition:
          'Other contracts in your portfolio of similar type, counterparty geography and tenor that the agent uses to anchor the proposed terms. Pulled via database_query at run time so the comparison is to your own book, not to an industry-wide benchmark.',
      },
    ],
  },

  'insights-force-majeure': {
    routeKey: 'insights-force-majeure',
    page_title: 'Force Majeure Monitor',
    purpose:
      'This page scans every contract you own for events that could trigger a force majeure clause, drafts the FM notice referencing exact clause numbers, calculates the financial impact, and queues the notice for human legal review. A force majeure clause is the contract provision that excuses a party from performance when an extraordinary event (regulation, natural disaster, grid event, market closure, sanctions) makes performance impossible or commercially unreasonable.\n\nThe scan is run on demand from the Run FM Scan button. The contractiq-force-majeure-monitor agent branches its scan plan on contract type (PPA, gas, tolling, virtual PPA, metals) and pulls live signals from ENTSO-E, Ember Climate and ECB plus web search for regulatory and disaster news. A pre-flight check in the API short-circuits the scan when the portfolio is empty so the agent does not invent a trigger out of thin air.\n\nA realistic note. The trigger description and the draft notice are LLM-written. The financial-impact figure is model arithmetic against the contract pricing fields. Nothing is sent to the counterparty until a human marks the notice as sent. The Dismiss path is there because the agent will sometimes raise a borderline trigger that the legal team decides is not worth pursuing.',
    sections: [
      {
        title: 'Run FM Scan button (header)',
        what_it_shows:
          'The header button that kicks off a scan across every contract you own. Shows a spinner while running and a toast banner (green ok, amber warning, red error) when finished.',
        agent_slug: 'contractiq-force-majeure-monitor',
        tools_used: ['database_query', 'entso_e_tool', 'ember_tool', 'ecb_rates_tool', 'tavily_search', 'financial_calculator', 'current_time'],
        data_quality: 'mixed',
        layman_note:
          'One click runs the agent across the whole portfolio. The toast tells you how many notices were created (could be zero) and whether the agent skipped because the portfolio was empty or returned unparseable output.',
      },
      {
        title: 'Notice list (severity-coded)',
        what_it_shows:
          'One card per FM notice created by a past scan, sorted newest first. Each card carries a severity badge (critical red, warning amber, info cyan), the trigger type and description, the financial impact in USD, the deadline to notify and the current notice status.',
        agent_slug: 'contractiq-force-majeure-monitor',
        tools_used: ['database_query'],
        data_quality: 'mixed',
        layman_note:
          'The list itself is a database read, the severity and impact figures on each row are what the agent wrote at the original run. Re-running the scan does not retroactively update prior notices — it creates new rows.',
      },
      {
        title: 'Applicable Clauses (expanded card)',
        what_it_shows:
          'Inside an expanded notice, a list of the contract clauses the agent identified as relevant to this trigger. Each line shows the clause number, the clause title and an excerpt from the contract text in italic.',
        agent_slug: 'contractiq-force-majeure-monitor',
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The clause number and excerpt come from the extracted-clauses table written by the upload pipeline. The agent picks them, but the text is real contract text — verify against the source PDF before quoting in a counterparty notice.',
      },
      {
        title: 'Draft Notice',
        what_it_shows:
          'The complete force majeure notice the agent drafted, displayed as monospace text with line wrapping. References the specific clause numbers, names the triggering event with the exact regulatory or market signal, and proposes remediation language.',
        agent_slug: 'contractiq-force-majeure-monitor',
        tools_used: ['entso_e_tool', 'ember_tool', 'ecb_rates_tool', 'tavily_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'This is a starting draft, not a ready-to-send notice. Legal review is required before transmission. The agent does not have access to your governing-law boilerplate or your house notification clauses.',
      },
      {
        title: 'Mark Sent / Dismiss buttons',
        what_it_shows:
          'Two human-action buttons at the bottom of an expanded card. Mark Sent records that the notice has been transmitted to the counterparty. Dismiss closes the notice without action.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These actions update the notice status in the database. The agent never marks a notice as sent. The state transition is human-only.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GET /api/contractiq/insights/force-majeure/notices',
        detail:
          'Loads the persisted notices for the user, newest first. No agent runs on load.',
      },
      {
        step: 2,
        label: 'User clicks Run FM Scan',
        detail:
          'Browser POSTs to /api/contractiq/insights/force-majeure/scan with an empty body. The router pre-flights a contract count and returns an empty_portfolio warning if you have no contracts.',
      },
      {
        step: 3,
        label: 'API calls contractiq-force-majeure-monitor',
        detail:
          'The agent receives "Run a full force majeure scan across all my contracts" as the message. It branches its scan plan on contract type and runs its tools in parallel where possible.',
      },
      {
        step: 4,
        label: 'Agent emits a notices array',
        detail:
          'Each entry includes contract_id, trigger_type, trigger_description, severity, applicable_clauses, financial_impact_usd, draft_notice, and deadline_to_notify_iso. The router validates each contract_id is owned by the user before persisting.',
      },
      {
        step: 5,
        label: 'Notices land in contractiq_fm_notices with status awaiting_review',
        detail:
          'The browser reloads, the new notices appear in the list. The toast tells you how many were created.',
      },
      {
        step: 6,
        label: 'User reviews and clicks Mark Sent or Dismiss',
        detail:
          'POST /api/contractiq/insights/force-majeure/notices/{id}/review with a status field. Updates the row. No agent run.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'agent', 'agentic_workflow', 'guardrail', 'ppa']),
      {
        term: 'Force majeure',
        definition:
          'A contract clause that excuses a party from performance when an extraordinary, unforeseeable event outside their control prevents them from meeting their obligations. Common triggers include natural disasters, war, sanctions, regulatory change, grid emergency and pandemic.',
      },
      {
        term: 'FM notice',
        definition:
          'The formal letter sent to the counterparty invoking a force majeure clause. Must reference the specific clause number, describe the triggering event, state when performance was affected, and propose remediation. The draft on this page is a starting point for legal review.',
      },
      {
        term: 'Trigger type',
        definition:
          'The category of event the agent identified as potentially activating FM. The current taxonomy covers regulation, grid event, market closure, sanctions, weather, and other.',
      },
      {
        term: 'Financial impact (USD)',
        definition:
          'The agent\'s estimate of the dollar effect of the trigger on the contract, computed from the contract pricing fields and the size of the disruption. It is model arithmetic, not a settlement figure.',
      },
      {
        term: 'Deadline to notify',
        definition:
          'The date by which the FM notice must be transmitted to the counterparty under the contract\'s notification provisions. The agent pulls this from the parsed notification clauses where available, otherwise leaves it null.',
      },
    ],
  },

  'insights-hedge': {
    routeKey: 'insights-hedge',
    page_title: 'Hedge Advisor',
    purpose:
      'This page builds a right-sized hedge recommendation for any contract with floating-price exposure. A hedge is a second financial position taken to offset the price risk on the first — if the contract loses value when gas prices rise, the hedge gains value when gas prices rise, and the two cancel each other out within the chosen tolerance. The contractiq-hedge-advisor agent designs the structures, sizes them to your tolerance, and writes a rationale that names the trade-offs.\n\nYou pick a contract from your portfolio, choose a risk tolerance (low for maximum hedge coverage, medium for a balanced position, high for the cheapest minimal hedge), and click Recommend. The agent identifies the exposure type (commodity price, FX, index), proposes three structures appropriate to the family (swap, collar, cap+floor, FX forward), computes a premium and a residual risk for each, and marks one as the recommended choice with a written rationale.\n\nA realistic note. The premium and the residual-risk figures are model estimates calibrated to current forward levels and historical volatility. They are not broker quotes. The agent draws on a fast ML prior (contractiq-risk-tier-predictor) before any heavier VaR maths so the recommendation arrives in seconds rather than minutes, with the trade-off that the prior is a learned shortcut rather than a full simulation.',
    sections: [
      {
        title: 'Recommend Hedge form (contract + tolerance)',
        what_it_shows:
          'A teal-bordered card at the top with a contract dropdown, a risk-tolerance selector (low / medium / high) and the Recommend button. The dropdown lists every contract you own.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The dropdown is loaded from your contracts table. Nothing model-driven happens until you click Recommend.',
      },
      {
        title: 'Hedge recommendation card (header)',
        what_it_shows:
          'For each persisted recommendation, a collapsed header row showing the contract title, the exposure type, the notional amount with currency, the tenor in months and the recommended structure in teal.',
        agent_slug: 'contractiq-hedge-advisor',
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The header values are what the agent wrote on the original run, read from the contractiq_hedge_recommendations table. No re-run on page load.',
      },
      {
        title: 'Structures grid (recommended marked)',
        what_it_shows:
          'When expanded, a three-card grid of the proposed structures. Each card lists the structure type (swap, collar, cap+floor, FX forward), premium in USD, cost as a percent of notional, residual risk text, a description and a pros/cons note. The recommended card has a star badge and a teal border.',
        agent_slug: 'contractiq-hedge-advisor',
        tools_used: ['database_query', 'entso_e_tool', 'ember_tool', 'ecb_rates_tool', 'financial_calculator', 'ml_model_tool'],
        data_quality: 'agent-simulated',
        layman_note:
          'The cost-percent and residual-risk values are model output, not broker quotes. The recommended choice is the one the agent judges to best fit your stated tolerance. Override based on counterparty preferences and execution constraints the agent does not see.',
      },
      {
        title: 'Rationale (markdown)',
        what_it_shows:
          'A markdown block beneath the structures explaining why the agent picked this structure: the exposure decomposition, the trade-offs against the other two structures, the residual risk after hedging, and any execution notes.',
        agent_slug: 'contractiq-hedge-advisor',
        tools_used: [],
        data_quality: 'agent-simulated',
        layman_note:
          'This is the agent explaining itself. Useful for understanding the trade-off the recommendation embodies. Read it before defending the choice to your committee.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GET /api/contractiq/insights/hedge',
        detail:
          'Loads existing hedge recommendations from the contractiq_hedge_recommendations table. The contracts list is loaded in parallel via /api/contractiq/contracts.',
      },
      {
        step: 2,
        label: 'User selects a contract and tolerance, clicks Recommend',
        detail:
          'Browser POSTs to /api/contractiq/insights/hedge/{contract_id}/recommend with a risk_tolerance field (low / medium / high).',
      },
      {
        step: 3,
        label: 'API calls contractiq-hedge-advisor via _call_abenix',
        detail:
          'The router builds a contract-specific message naming the contract and the requested tolerance. The agent branches on contract type and runs its tool plan.',
      },
      {
        step: 4,
        label: 'Agent runs ml_model + market tools + financial maths',
        detail:
          'ml_model_tool runs the contractiq-risk-tier-predictor as a fast prior. entso_e / ember_climate / ecb_rates pull live forward levels for the underlying. financial_calculator sizes the premiums and computes residual risk. database_query reads the contract pricing fields.',
      },
      {
        step: 5,
        label: 'Agent emits structures + recommended_structure + rationale',
        detail:
          'The router persists the result into contractiq_hedge_recommendations with status completed. The browser reloads the list.',
      },
      {
        step: 6,
        label: 'UI renders header, three-card grid and rationale markdown',
        detail:
          'No further computation in the browser. The recommended card is identified by matching recommended_structure to the structure type or name.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'basis_risk', 'mtm', 'agent', 'forward_curve', 'monte_carlo']),
      {
        term: 'Hedge structure',
        definition:
          'A defined combination of financial positions designed to offset a specific price exposure. Common families are swap (lock in a fixed price), collar (cap the upside and floor the downside), cap+floor (buy protection above a strike, sell protection below), FX forward (lock in a future exchange rate).',
      },
      {
        term: 'Premium (hedge)',
        definition:
          'The upfront cost of buying the hedge, in dollars. Swaps usually have zero or near-zero premium because the cash flows net out. Options-based structures (collar, cap+floor) typically carry a non-zero premium because you are buying protection.',
      },
      {
        term: 'Residual risk',
        definition:
          'The portion of the original exposure that remains after the hedge is in place. Hedging is never perfect — a low-tolerance hedge leaves little residual but costs more, a high-tolerance hedge is cheap but leaves more risk on the table.',
      },
      {
        term: 'Risk tolerance (low / medium / high)',
        definition:
          'The agent\'s tolerance setting. Low requests maximum hedge coverage and accepts a higher premium. Medium balances cost and coverage. High asks for the cheapest minimal hedge and leaves more residual risk.',
      },
      {
        term: 'Exposure type',
        definition:
          'The category of price risk the agent identified on the contract — commodity-price (floating gas, power, metal), FX (revenue or cost in a non-base currency), or index (CPI, RPI, libor-linked). Drives which structures the agent considers.',
      },
    ],
  },

  'insights-version-diff': {
    routeKey: 'insights-version-diff',
    page_title: 'Version Diff',
    purpose:
      'This page compares two versions of a contract semantically — not just textually — and produces a prioritised reviewer summary for the business team. A semantic diff means the agent looks at meaning, not at characters. A renamed defined term, a paragraph re-ordering, a clause split into two does not count as a change; a tightened liability cap, a loosened indemnity, a new termination right does.\n\nYou pick a base contract and a new contract from your portfolio, both already uploaded and clause-extracted. The contractiq-version-diff agent loads both contracts via portfolio_energy_contracts.get_record, walks the clause set, classifies each change as tightened, loosened, added, removed or unchanged, rates the impact (low, medium, high, critical), and writes an overall impact verdict (favourable, adverse, neutral, mixed) plus a summary line.\n\nA realistic note. The classification is LLM-judged against the clause text the upload pipeline extracted. If the extractor missed a clause in one version, the diff cannot see what changed there. Re-extract a contract on the detail page if the diff result looks short. The impact rating is opinion, not policy — your in-house legal taxonomy may classify the same change differently.',
    sections: [
      {
        title: 'Compare Two Contracts form (base → new)',
        what_it_shows:
          'A pink-bordered card with a Base (older) dropdown, an arrow, a New (newer) dropdown and the Run Diff button. Both dropdowns list every contract you own. The button is disabled until both are selected and the two contracts differ.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The dropdowns read your contracts table. No model runs until you press Run Diff.',
      },
      {
        title: 'Diff card header (overall impact + change count)',
        what_it_shows:
          'For each persisted diff, a collapsed row showing the base contract title, an arrow, the new contract title, the overall-impact badge (favourable, adverse, neutral, mixed) and a one-line summary. The footer shows the number of changes and the run date.',
        agent_slug: 'contractiq-version-diff',
        tools_used: ['database_query'],
        data_quality: 'mixed',
        layman_note:
          'The overall-impact badge is the agent\'s verdict. The summary line is its one-sentence explanation. Use to prioritise which diffs to open first.',
      },
      {
        title: 'Change list (per-clause)',
        what_it_shows:
          'When expanded, one card per detected change. Each card shows the clause type, an icon for the change kind (tightened, loosened, added, removed, unchanged), an impact badge, the before text in red, the after text in green and a rationale in italic.',
        agent_slug: 'contractiq-version-diff',
        tools_used: ['database_query'],
        data_quality: 'mixed',
        layman_note:
          'The before and after text is what the upload extractor wrote at ingest time for each version — real contract text, just possibly slightly cleaned. The change-kind and impact labels are the agent\'s judgement, supported by the rationale line.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GET /api/contractiq/insights/version-diff',
        detail:
          'Loads persisted diffs from contractiq_version_diffs, newest first. Contracts list is loaded in parallel.',
      },
      {
        step: 2,
        label: 'User picks base, new and clicks Run Diff',
        detail:
          'Browser POSTs to /api/contractiq/insights/version-diff with base_contract_id and new_contract_id. The router validates both contracts belong to the user.',
      },
      {
        step: 3,
        label: 'API calls contractiq-version-diff via _call_abenix',
        detail:
          'The agent uses portfolio_energy_contracts.get_record to load both contracts and database_query for any direct clause SELECTs it needs. No external tools — this is a pure document-comparison agent.',
      },
      {
        step: 4,
        label: 'Agent emits changes + overall_impact + summary',
        detail:
          'Each change carries clause_type, change_kind (tightened / loosened / added / removed / unchanged), impact (low / medium / high / critical), before, after and rationale. The overall_impact is favourable, adverse, neutral or mixed.',
      },
      {
        step: 5,
        label: 'Router persists the diff and returns it',
        detail:
          'Result lands in contractiq_version_diffs with status completed. The browser reloads, the new diff appears at the top.',
      },
      {
        step: 6,
        label: 'UI renders the header + change list',
        detail:
          'No further computation in the browser. Icons and impact badges are styled from the change_kind and impact fields.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'agent', 'clause_taxonomy', 'llm_as_judge']),
      {
        term: 'Semantic diff',
        definition:
          'A comparison of two contract versions based on meaning rather than text. Renamed defined terms, re-ordered paragraphs and clauses split across sections do not count as changes. Tightened caps, loosened indemnities and new rights do.',
      },
      {
        term: 'Change kind (tightened / loosened / added / removed / unchanged)',
        definition:
          'How the agent classifies each detected change. Tightened means the new version is stricter on the noted party. Loosened means more permissive. Added and removed are self-explanatory. Unchanged means the clause is present in both and the wording differences are immaterial.',
      },
      {
        term: 'Impact rating (low / medium / high / critical)',
        definition:
          'How much the change matters in dollar or risk terms, in the agent\'s judgement. Critical means it changes the headline economics or shifts a material right. Low means cosmetic or de minimis.',
      },
      {
        term: 'Overall impact (favourable / adverse / neutral / mixed)',
        definition:
          'The agent\'s one-word verdict on whether the new version is net better, worse, neutral or split for the calling party. Treat as a triage signal, not a binding legal opinion.',
      },
      {
        term: 'Reviewer summary',
        definition:
          'The one-line description shown at the top of the diff card. Designed for a busy reviewer who needs to decide in five seconds whether the diff is worth opening.',
      },
    ],
  },

  'insights-reconciliation': {
    routeKey: 'insights-reconciliation',
    page_title: 'Settlement Reconciliation',
    purpose:
      'This page reconciles a counterparty invoice against the matching contract. The contractiq-settlement-reconciler agent recomputes what should have been invoiced (with escalation, indexation and FX where the contract requires it), flags line-item discrepancies in dollar terms, and drafts a dispute letter when the variance crosses a material threshold. The point is to catch invoice errors and disputed line items before they are paid, in seconds rather than the days a human spreadsheet review would take.\n\nYou pick a contract, give the invoice period and the headline invoice amount, optionally attach the invoice file (text only in v1), and click Reconcile. The agent loads the contract pricing fields, runs financial_calculator to recompute each line item under the contract maths, and outputs an expected amount, the variance, the line-item breakdown, and a dispute letter if the variance exceeds the threshold.\n\nA realistic note. The expected amount is the agent doing arithmetic against the parsed contract terms. If a pricing field was missed at extraction, the recompute will use whatever the agent could see and the variance may be misleading. Always sanity-check the line-item table before lifting the dispute letter into a real one.',
    sections: [
      {
        title: 'Reconcile an Invoice form (contract / period / amount / file)',
        what_it_shows:
          'A cyan-bordered form at the top with contract dropdown, period text field, invoice amount in USD, and an optional text-file attachment. The Reconcile button is disabled until the contract and amount are populated.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The contract dropdown reads your contracts table. The form submission is a multipart upload — no agent runs until Reconcile is pressed.',
      },
      {
        title: 'Reconciliation card header (variance pill)',
        what_it_shows:
          'For each persisted reconciliation, a collapsed row showing an icon (alert when variance > 1%, check otherwise), the invoice period, the file name if attached, the invoice amount, the dollar variance and the percent variance.',
        agent_slug: 'contractiq-settlement-reconciler',
        tools_used: ['database_query'],
        data_quality: 'mixed',
        layman_note:
          'A green check is the agent reporting that the invoice matched the contract maths within tolerance. A red alert is saying it did not. Open the row to see why.',
      },
      {
        title: 'Invoiced vs Expected vs Variance tiles',
        what_it_shows:
          'A three-column tile row inside the expanded card showing the headline invoiced amount, the agent\'s expected amount, and the variance with sign-aware colouring.',
        agent_slug: 'contractiq-settlement-reconciler',
        tools_used: ['financial_calculator', 'entso_e_tool', 'ember_tool', 'ecb_rates_tool'],
        data_quality: 'agent-simulated',
        layman_note:
          'The expected number is the model recomputing the invoice from the contract pricing fields. For index-linked components it may have pulled live levels at run time. Variance is invoiced minus expected.',
      },
      {
        title: 'Line Items',
        what_it_shows:
          'A list of cards inside the expanded view, one per invoice line. Each shows the line description, invoiced amount, expected amount, dollar variance, percent variance and an explanation line in italic.',
        agent_slug: 'contractiq-settlement-reconciler',
        tools_used: ['financial_calculator'],
        data_quality: 'agent-simulated',
        layman_note:
          'The line-item table is where the agent shows its work. If a line variance does not match your expectation, read the explanation to see which contract field the agent used and whether the extractor got it right.',
      },
      {
        title: 'Draft Dispute Letter',
        what_it_shows:
          'When the variance is material, an amber-bordered block with the agent\'s drafted dispute letter in monospace. References the contract, names the disputed line items, quantifies the variance and proposes remediation language.',
        agent_slug: 'contractiq-settlement-reconciler',
        tools_used: [],
        data_quality: 'agent-simulated',
        layman_note:
          'A starting draft only. Legal review is required before transmission. The agent does not know your house dispute boilerplate or your governing-law notification clauses.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GET /api/contractiq/insights/reconciliation',
        detail:
          'Loads persisted reconciliations from contractiq_reconciliations, newest first. Contracts list loaded in parallel.',
      },
      {
        step: 2,
        label: 'User fills the form and clicks Reconcile',
        detail:
          'Browser POSTs multipart to /api/contractiq/insights/reconciliation/upload with contract_id, invoice_period, invoice_amount and an optional file. The router validates the contract belongs to the user.',
      },
      {
        step: 3,
        label: 'API persists a running row and calls contractiq-settlement-reconciler',
        detail:
          'A contractiq_reconciliations row is created with status running before the agent call. The router calls _call_abenix(user, "contractiq-settlement-reconciler", msg). The message includes the contract id, the title, the period and the invoice amount, plus the invoice text if a file was attached.',
      },
      {
        step: 4,
        label: 'Agent runs its tool plan',
        detail:
          'portfolio_energy_contracts loads the contract and its pricing fields, database_query reads historical settlements, financial_calculator recomputes the expected amount with escalation and indexation, entso_e / ember_climate / ecb_rates pull index levels when the contract is index-linked.',
      },
      {
        step: 5,
        label: 'Agent emits expected_amount + variance + line_items + dispute_letter',
        detail:
          'The router updates the persisted row with the structured fields and flips status to completed. On parse failure status moves to failed with the raw output in error_message.',
      },
      {
        step: 6,
        label: 'UI renders header, three-tile compare, line items and dispute letter',
        detail:
          'No further computation in the browser. The variance colouring is computed from the sign of variance_amount.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'mtm', 'agent', 'agentic_workflow', 'guardrail']),
      {
        term: 'Settlement reconciliation',
        definition:
          'The process of checking that a counterparty invoice matches what the contract says you should have been invoiced. Catches arithmetic errors, missed escalations, wrong index references, FX mistakes and outright billing fraud.',
      },
      {
        term: 'Expected amount',
        definition:
          'The agent\'s recomputed invoice total, built from the contract pricing fields plus any required indexation, escalation and FX conversion. Compared against the actual invoice to produce the variance.',
      },
      {
        term: 'Variance (amount and percent)',
        definition:
          'The difference between the invoiced amount and the expected amount, in dollars and as a percent. Positive variance means over-billing, negative means under-billing. The dispute threshold is 1% in this build.',
      },
      {
        term: 'Line item',
        definition:
          'A single component of the invoice — capacity payment, energy payment, escalation, indexation adjustment, FX translation. Each is recomputed separately and shown with its own variance so the agent can localise where the disagreement sits.',
      },
      {
        term: 'Dispute letter',
        definition:
          'The agent-drafted notice flagging the disputed line items to the counterparty. Generated only when the variance is material. Treat as a starting draft for legal review, not as a ready-to-send notice.',
      },
      {
        term: 'Indexation',
        definition:
          'Contract clause that adjusts price by a published index (CPI, gas index, power index) at defined intervals. Indexation errors are a common source of invoice disputes because the wrong index value or the wrong reset date can change the headline total.',
      },
    ],
  },

  'insights-families': {
    routeKey: 'insights-families',
    page_title: 'Contract Families',
    purpose:
      'This page lets you group a master contract with its amendments, side letters and related agreements so the rest of the product can reason across them as one document set. There is no agent on this page. It is a thin CRUD UI sitting on top of the contractiq_contract_families table. Creating a family does not extract anything, run any LLM, or change the underlying contracts — it only writes a grouping record.\n\nThe value lands later. Once a family exists, other surfaces (chat, version diff, valuation, force majeure scan) can scope to the whole family instead of a single contract. A renewal copilot run against a family considers the master plus every amendment when assembling the negotiation packet, rather than treating an amended contract as if the original were still untouched.\n\nA realistic note. The grouping is your judgement, not a model output. If you mis-flag a master, the only consequence is that downstream surfaces treat the wrong contract as the spine of the family. Edit the family from this page to fix it — no re-extraction or re-ingest is needed.',
    sections: [
      {
        title: 'New Family button (header)',
        what_it_shows:
          'The header button that opens the editor card. Used to start creating a new family. No agent run.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Opening this just shows the editor. Nothing is saved until you click Save in the editor.',
      },
      {
        title: 'Editor (New / Edit Family)',
        what_it_shows:
          'A purple-bordered card with the family name, optional description, master-contract dropdown, and a scrollable checkbox list of every contract you own for selecting members. Save and Cancel buttons at the bottom.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Pure form. The dropdown and checkbox list load from your contracts table. The Save action POSTs or PUTs to the families endpoint.',
      },
      {
        title: 'Family list (cards)',
        what_it_shows:
          'One card per family showing the family name and description. Below the name, the master contract is shown with a crown icon and an amber tag. Every member contract is listed below with a file icon. Edit and delete buttons sit in the top-right corner.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Pure database read of the contractiq_contract_families table, joined to the contracts list for the titles. No model output anywhere on the card.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GET /api/contractiq/insights/families',
        detail:
          'Loads every family owned by the user, ordered by most recently updated. Contracts list is loaded in parallel for the title lookup.',
      },
      {
        step: 2,
        label: 'User clicks New Family or Edit, fills the form, clicks Save',
        detail:
          'For new families, POST /api/contractiq/insights/families with family_name, description, master_contract_id and member_contract_ids. For edits, PUT /api/contractiq/insights/families/{family_id} with the same payload.',
      },
      {
        step: 3,
        label: 'API writes the row',
        detail:
          'No agent. The router validates the user owns each contract referenced and writes the record. master_contract_id may be null. member_contract_ids is a JSON array.',
      },
      {
        step: 4,
        label: 'User clicks the trash icon to delete',
        detail:
          'DELETE /api/contractiq/insights/families/{family_id}. The router checks ownership and removes the row.',
      },
      {
        step: 5,
        label: 'UI reloads the list on every mutation',
        detail:
          'No further computation in the browser. Cards re-render from the latest server payload.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'agent', 'pipeline']),
      {
        term: 'Contract family',
        definition:
          'A named grouping of related contracts — a master and its amendments, or a master and its side letters. Stored as a single row that lists the master contract id and an array of member contract ids. The grouping is human judgement, not a model output.',
      },
      {
        term: 'Master contract',
        definition:
          'The spine document of a family — typically the original signed agreement. Amendments and side letters are read on top of the master to determine the current state of the relationship. Optional: a family may have no designated master.',
      },
      {
        term: 'Amendment',
        definition:
          'A later document that modifies the master. Could be a price reset, a tenor extension, a re-papered set of clauses. Should be added as a member of the same family so downstream surfaces apply them together.',
      },
      {
        term: 'Side letter',
        definition:
          'A separate agreement that exists alongside the master and modifies its application without amending the text. Often used for commercial terms the parties prefer not to surface in the main contract. Should also be a family member.',
      },
      {
        term: 'Cross-document reasoning',
        definition:
          'The mode where an agent or surface considers every member of a family together rather than reading the master alone. Version diff, renewal copilot, valuation and the chat agent all benefit from a properly grouped family.',
      },
    ],
  },

  'metals-compliance': {
    routeKey: 'metals-compliance',
    page_title: 'Compliance Audit',
    purpose:
      'Per-contract standards audit for the precious-metals book. For each contract in your portfolio this page runs (or re-runs) the metals compliance auditor and shows the overall score, the count of block-level issues, the count of clarification requests, a verdict per standard, and any references to superseded versions of those standards.\n\nThe standards covered are LBMA Good Delivery and Responsible Gold Guidance, LPPM, OECD Due Diligence Guidance, RJC chain of custody, Dodd-Frank Section 1502, EU 2017/821, ISO 9001 and 14001, Swiss PMCA, HMRC VAT 701/14, REACH and sanctions screening (OFAC, EU consolidated). Each verdict is the LLM judgement against the standard text the knowledge base returns, with the citation line shown below the verdict so you can check the work before treating any pass or fail as final.\n\nThis page does not negotiate or rewrite clauses. It surfaces what the agent found. Use the [contract detail](/contracts) page to act on a verdict.',
    sections: [
      {
        title: 'Page header + contract list',
        what_it_shows:
          'One row per contract in the tenant — title, counterparty, and (once an audit has run) overall score, block-level issue count and clarification count. Rows without a prior audit show only the Audit button.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These rows come straight from the contracts and metals-compliance tables. No agent is invoked just to render the list. The pills only appear after the audit has been run at least once on that contract.',
      },
      {
        title: 'Audit / Re-audit action',
        what_it_shows:
          'Posts to /api/contractiq/metals/contracts/{id}/compliance-audit. That endpoint dispatches the compliance auditor agent, persists the verdict envelope into the metals-compliance table, and shows an "Audit complete" toast on success or the error message on failure.',
        agent_slug: 'contractiq-metals-compliance-auditor',
        tools_used: ['database_query', 'knowledge_search', 'web_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'The auditor loads the contract text, pulls the relevant clauses from each standard out of the knowledge base, and writes a pass / fail / not-applicable / unclear judgement per standard. A web search is allowed only to confirm a refiner is still on a current Good Delivery List.',
      },
      {
        title: 'Detail panel — per-standard verdicts and superseded references',
        what_it_shows:
          'Expanding a row shows the audit summary line, then one card per verdict with the standard name, the citation line, and the agent\'s notes. Below the verdicts, a "Superseded references" block lists any clause that points to a withdrawn version of a standard (the agent flags GOFO references post-2023 and any pre-2022 contract without a Russian-origin exclusion).',
        agent_slug: 'contractiq-metals-compliance-auditor',
        tools_used: ['database_query', 'knowledge_search'],
        data_quality: 'mixed',
        layman_note:
          'The citation line is anchored to the real standard text the knowledge base returned. The pass / fail call is the LLM\'s reading of that text against the contract. Read the citation before relying on a verdict for a regulatory submission.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Page loads contracts and prior audits in parallel',
        detail:
          'Two GETs: /api/contractiq/contracts for the tenant\'s contracts and /api/contractiq/metals/compliance for any saved audit envelopes. Rows are joined by contract_id in the browser.',
      },
      {
        step: 2,
        label: 'User clicks Audit on a contract',
        detail:
          'POST /api/contractiq/metals/contracts/{id}/compliance-audit. The router invokes the AgentForge SDK against contractiq-metals-compliance-auditor.',
      },
      {
        step: 3,
        label: 'Agent runs knowledge_search and database_query',
        detail:
          'The auditor loads the contract text and prior metals extraction via database_query, pulls the canonical clause text for LBMA, OECD, RJC, ISO and the sanctions lists via knowledge_search, and may call web_search to confirm a refiner is still on the current Good Delivery List.',
      },
      {
        step: 4,
        label: 'API persists the verdict envelope',
        detail:
          'The structured JSON returned by the agent is written into the metals_compliance table with overall_score, block_level_issues, clarification_requests, verdicts and superseded_references columns.',
      },
      {
        step: 5,
        label: 'UI reloads and the row re-renders',
        detail:
          'The browser calls load() again so the contract row picks up the new score and verdict list without a full page reload.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'guardrail', 'counterparty']),
      {
        term: 'LBMA',
        definition:
          'London Bullion Market Association. The trade body that publishes the Good Delivery List of accepted gold and silver refiners and the Responsible Gold Guidance audit standard. Bullion that does not come from an LBMA-listed refiner is hard to sell into the wholesale London market.',
      },
      {
        term: 'LPPM',
        definition:
          'London Platinum and Palladium Market. The equivalent of the LBMA for platinum and palladium — it publishes the Good Delivery List for those two metals and the auditing rules around it.',
      },
      {
        term: 'Good Delivery List',
        definition:
          'The roster of refiners whose bars are accepted at face value by the London wholesale bullion market. LBMA publishes the lists for gold and silver, LPPM publishes them for platinum and palladium. A refiner can be active, suspended, delisted or never listed, and the status changes the moment an audit finding goes against them.',
      },
      {
        term: 'OECD Due Diligence Guidance',
        definition:
          'The OECD\'s five-step framework that companies are expected to use to keep conflict minerals and sanctioned-origin material out of their supply chain. Step one is a management system, step five is independent assurance. The LBMA RGG audit checks each step.',
      },
      {
        term: 'Section 1502 (Dodd-Frank)',
        definition:
          'The US securities-law provision that requires public companies to disclose use of tin, tungsten, tantalum and gold (3TG) sourced from the DRC and adjoining countries. ContractIQ checks whether a contract references it because absence on a metals offtake is a red flag.',
      },
      {
        term: 'EU Regulation 2017/821',
        definition:
          'The EU\'s conflict-minerals regulation, in force since 2021. Mirrors the OECD DDG for 3TG importers above de minimis volumes. A metals contract sold into the EU should reference it or explain why it is out of scope.',
      },
      {
        term: 'Swiss PMCA',
        definition:
          'The Swiss Precious Metals Control Act and its implementing ordinance. Governs hallmarking, refiner registration and assay control on metal trading through Switzerland. Loco-Zurich contracts often reference it.',
      },
    ],
  },

  'metals-disputes': {
    routeKey: 'metals-disputes',
    page_title: 'Dispute Risk Scorer',
    purpose:
      'Per-contract dispute exposure scorer. For each metals contract the dispute scorer agent reads the contract text plus any prior metals extraction, and returns a five-dimension breakdown (assay, weight, brand, late delivery, sanctioned origin), an aggregate score, a tier (low, elevated or high), an expected loss in USD, and a list of top recommendations.\n\nThe expected-loss number is a model output, not a contingency reserve. It is built from typical industry settlement size against the dimension that scored the highest probability of dispute, scaled by your contract notional. Use it to triage which contracts deserve a legal review before delivery, not as an audited financial provision.',
    sections: [
      {
        title: 'Page header + contract list',
        what_it_shows:
          'One row per contract — title, counterparty, then once scored the tier pill (low / elevated / high), the expected loss in USD, and the expected loss as a percent of notional. Rows without a prior score show only the Score button.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These rows come from the contracts and metals-disputes tables in your tenant. The page does not re-score on every load — pills only show up after the scorer has been run at least once on that contract.',
      },
      {
        title: 'Score / Re-score action',
        what_it_shows:
          'Posts to /api/contractiq/metals/contracts/{id}/dispute-risk. That endpoint dispatches the dispute scorer agent and persists the result envelope into the metals-disputes table.',
        agent_slug: 'contractiq-metals-dispute-scorer',
        tools_used: ['database_query', 'knowledge_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'The scorer loads contract and extraction rows via database_query and pulls comparable historical disputes from the metals knowledge base via knowledge_search. There is no live web call in this flow.',
      },
      {
        title: 'Detail panel — per-dimension cards and top recommendations',
        what_it_shows:
          'Expanding a row shows one card per dimension (assay, weight, brand, late-delivery, sanctioned-origin) with a 0..1 score, a USD expected exposure for that dimension, the agent\'s rationale, and a recommended mitigation. Below those is a "Top recommendations" block summarising the highest-impact actions.',
        agent_slug: 'contractiq-metals-dispute-scorer',
        tools_used: ['database_query', 'knowledge_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'The dimension scores and the expected-exposure dollars are model output. The rationale text is meant to make the score auditable — it should reference the assay tolerance, the brand list or the loco that drove the number. If the rationale is vague, the score is too.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Page loads contracts and prior scores in parallel',
        detail:
          'Two GETs: /api/contractiq/contracts and /api/contractiq/metals/disputes. The browser joins them by contract_id and keeps only the latest dispute row per contract.',
      },
      {
        step: 2,
        label: 'User clicks Score on a contract',
        detail:
          'POST /api/contractiq/metals/contracts/{id}/dispute-risk. The router invokes the AgentForge SDK against contractiq-metals-dispute-scorer.',
      },
      {
        step: 3,
        label: 'Agent runs database_query and knowledge_search',
        detail:
          'The scorer pulls contract text and prior metals extraction via database_query, then queries the knowledge base for historical comparable disputes via knowledge_search — assay disputes around 0.05% tolerance, weight variance disputes at 1-2% of notional, late-delivery damages by week, sanctioned-origin claims, and forced-unwind cases from list ejections.',
      },
      {
        step: 4,
        label: 'API persists the result',
        detail:
          'The structured envelope (aggregate_score, tier, expected_loss_usd, dimensions array, top_recommendations array) is written into the metals_disputes table.',
      },
      {
        step: 5,
        label: 'UI reloads and the row re-renders',
        detail:
          'Browser calls load() again. The pill, expected-loss and detail panel reflect the new envelope.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'agent', 'pipeline', 'guardrail']),
      {
        term: 'Assay tolerance',
        definition:
          'The narrow band around the agreed fineness inside which the buyer accepts the metal without a price adjustment. Gold is typically 0.05% (5 parts in 10,000). Disputes happen when the buyer\'s assay comes back outside the band and the seller\'s assay disagrees.',
      },
      {
        term: 'Umpire clause',
        definition:
          'The contract clause that names a neutral third assayer (often a referee lab on a published list) to decide a binding fineness or weight result when buyer and seller disagree. Its absence sharply raises dispute risk on doré and concentrate trades.',
      },
      {
        term: 'Loco premium',
        definition:
          'The price uplift (or discount) for delivery at a non-London vault. Loco-Zurich and loco-Shanghai typically trade above loco-London because of customs frictions and onward sale demand.',
      },
      {
        term: 'Notional',
        definition:
          'The face value of the contract — bar weight times reference price plus any fixed premium. The dispute scorer expresses the expected loss as both a USD figure and a percent of notional so you can compare risk across very different contract sizes.',
      },
      {
        term: 'List ejection',
        definition:
          'When LBMA or LPPM removes a refiner from the Good Delivery List. Outstanding contracts that named the refiner can be forced to unwind or to re-source bars from an active refiner, which usually crystallises a mark-to-market loss.',
      },
    ],
  },

  'metals-extract': {
    routeKey: 'metals-extract',
    page_title: 'Metals Extraction',
    purpose:
      'Second-pass extraction of metals-specific fields per contract. The standard contract extractor pulls the generic clauses (parties, term, notional, payment). This page runs the metals extractor on top of that to pull out fineness, bar weight and tolerance, good-delivery standard, accepted refiners, loco, delivery window, pricing reference and formula, settlement currency, assay method and tolerance, vaulting type, insurance coverage, treatment and refining charges, payable percentages per metal, and the sanctions clauses (Russian-origin exclusion, OFAC).\n\nThe agent uses null rather than guessing for fields the contract does not spell out and returns a confidence number. Treat any field with low confidence or a null on a high-value contract as a manual review item.',
    sections: [
      {
        title: 'Page header + contract list',
        what_it_shows:
          'One row per contract with title, counterparty and an Extract / Re-extract button. If extraction has run, the row shows a grid of every extracted field (Material, Fineness, Bar weight, GD standard, Loco, Pricing ref, Settlement, Assay, Vaulting, Insurance, Umpire clause, Russian-origin excluded, OFAC clause, Refiners accepted, TC/RC where applicable, Confidence).',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Rows come from contracts and metals-extractions tables in your tenant. The grid only renders after the extractor has been run. If a contract is missing the metals fields, click Extract to run the agent on it.',
      },
      {
        title: 'Extract / Re-extract action',
        what_it_shows:
          'Posts to /api/contractiq/metals/contracts/{id}/extract. That endpoint dispatches the metals extractor agent and persists the structured envelope into the metals-extractions table. Shows "Extraction complete" or the error message in a toast.',
        agent_slug: 'contractiq-metals-extractor',
        tools_used: ['database_query', 'knowledge_search', 'web_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'The extractor reads contract text via database_query, cross-checks the metals knowledge base for clause patterns via knowledge_search, and may verify a named refiner against the current LBMA/LPPM list via web_search. Output is strict JSON — any field it cannot find stays null rather than being invented.',
      },
      {
        title: 'Field grid — material, loco, pricing, assay, vaulting, sanctions',
        what_it_shows:
          'A grid of small Field tiles, each showing one extracted attribute. Includes the material form, the GD standard reference, the loco, the assay method and tolerance band, vaulting type, insurance minimum coverage, treatment and refining charges for concentrate or dore, and explicit yes/no on umpire clause, Russian-origin exclusion and OFAC clause.',
        agent_slug: 'contractiq-metals-extractor',
        tools_used: ['database_query', 'knowledge_search'],
        data_quality: 'mixed',
        layman_note:
          'Values are extracted from the contract text. Where the contract spelled the field out, the value is verbatim. Where the contract was ambiguous the agent left it null. Confidence at the bottom of the grid is the agent\'s self-score across the whole envelope.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Page loads contracts and prior extractions in parallel',
        detail:
          'Two GETs: /api/contractiq/contracts and /api/contractiq/metals/extractions. The browser builds a Map of latest extraction per contract.',
      },
      {
        step: 2,
        label: 'User clicks Extract on a contract',
        detail:
          'POST /api/contractiq/metals/contracts/{id}/extract. The router invokes the AgentForge SDK against contractiq-metals-extractor.',
      },
      {
        step: 3,
        label: 'Agent runs database_query, knowledge_search and (optionally) web_search',
        detail:
          'The extractor loads the contract text and the standard extractor\'s prior output via database_query, pulls metals-clause patterns from the knowledge base via knowledge_search, and may call web_search to confirm a named refiner is currently active on LBMA or LPPM.',
      },
      {
        step: 4,
        label: 'API persists the envelope',
        detail:
          'The JSON envelope (material, fineness_min, bar_weight_oz, good_delivery_standard, accepted_refiners, loco, pricing_reference, assay_method, vaulting_type and the rest) is written into the metals_extractions table.',
      },
      {
        step: 5,
        label: 'UI reloads the grid',
        detail:
          'Browser calls load() again. The Field tiles render directly from the saved row with no further computation.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'guardrail']),
      {
        term: 'Fineness',
        definition:
          'The proportion of pure metal in the bar, expressed as a decimal between 0 and 1 (so .9999 for four-nines gold). LBMA Good Delivery gold requires a minimum fineness of .995, four-nines is the wholesale norm.',
      },
      {
        term: 'Good Delivery bar',
        definition:
          'A bar that meets the LBMA (or LPPM) specification for weight, fineness, marks and refiner. A Good Delivery gold bar is roughly 400 troy ounces and stamped with the refiner\'s LBMA-recognised hallmark. Accepted at face value in London vaults.',
      },
      {
        term: 'Doré',
        definition:
          'An impure alloy of gold and silver that comes straight from a mine\'s gravity or smelter circuit, before final refining. Typically 70-95% precious metal. Buyers pay on a payable percentage and refine the rest themselves — so the contract economics are TC, RC and payables, not a flat per-ounce price.',
      },
      {
        term: 'Concentrate',
        definition:
          'Crushed ore enriched at the mine to remove waste rock, sold by tonne with a payable percentage per metal. Pricing is the metal value times payable minus a treatment charge (per tonne) and a refining charge (per ounce of contained metal).',
      },
      {
        term: 'Loco',
        definition:
          'The vault where the metal is recorded. Loco-London, loco-Zurich, loco-New York, loco-Shanghai, loco-Hong Kong, loco-Dubai and loco-Singapore are the main vaulting points. Each loco trades at a different premium vs the London reference.',
      },
      {
        term: 'TC / RC',
        definition:
          'Treatment Charge (per tonne of concentrate) and Refining Charge (per ounce of contained metal). The smelter / refiner is paid TC and RC out of the metal value. Higher TC/RC means tighter mining margins.',
      },
      {
        term: 'Pricing reference',
        definition:
          'The published index against which the contract\'s price is set. LBMA Gold AM / PM are the London auction prints, LPPM platinum and palladium are the equivalent. COMEX, Shanghai Gold Exchange and free-text formulas are also common.',
      },
      {
        term: 'Vaulting type',
        definition:
          'Allocated (specific numbered bars set aside for you), unallocated (a balance on the vault\'s books that they owe you in any bar), segregated (your bars in a labelled space) or mixed. Allocated is the safest for KYC and audit purposes.',
      },
    ],
  },

  'metals-loco': {
    routeKey: 'metals-loco',
    page_title: 'Loco + Delivery',
    purpose:
      'Per-contract loco and delivery analysis. The loco analyzer reads the contract\'s loco field (Zurich, London, New York, Shanghai and others), pulls a reference price per ounce, computes the loco premium against London as a percentage and as USD per ounce, then walks through the insurance, customs and tariff, chain-of-integrity, repatriation, vault-handover and cross-loco comparison sections.\n\nThe agent issues alerts where the loco terms are weak — missing all-risk insurance, undefined repatriation, or a chain of integrity that does not name a vault. Recommendations are paired with each alert so the legal team has a starting point.',
    sections: [
      {
        title: 'Page header + contract list',
        what_it_shows:
          'One row per contract with title, counterparty and (after analysis) a loco pill (loco zurich / london / new york / shanghai), the loco premium percent and the premium per ounce in USD.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The list comes from your contracts table joined to the metals-loco table. The premium figure only shows after the analyzer has run on that contract.',
      },
      {
        title: 'Analyze / Re-analyze action',
        what_it_shows:
          'Posts to /api/contractiq/metals/contracts/{id}/loco-analyze. That endpoint dispatches the loco analyzer agent and writes the result envelope into the metals-loco table.',
        agent_slug: 'contractiq-metals-loco-analyzer',
        tools_used: ['database_query', 'web_search', 'knowledge_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'The analyzer pulls the contract and the metals extraction via database_query, queries the knowledge base for the customs and tariff rules at the destination via knowledge_search, and uses web_search to fetch current loco premium reference levels.',
      },
      {
        title: 'Detail panel — Insurance, Customs & tariff, Chain of integrity, Repatriation, Vault handover, vs other loco',
        what_it_shows:
          'Six sub-sections rendered as key-value lists: Insurance (carrier, coverage type, minimum coverage percent), Customs & tariff (HS code, tariff schedule, VAT treatment), Chain of integrity (vault, custodian, audit interval), Repatriation (rights, notice period, cost burden), Vault handover (allocation type, identification protocol), and a vs-other-loco comparison if computed.',
        agent_slug: 'contractiq-metals-loco-analyzer',
        tools_used: ['database_query', 'knowledge_search', 'web_search'],
        data_quality: 'mixed',
        layman_note:
          'Values inside each panel come either from the contract text (insurance, repatriation, vault handover) or the knowledge base of customs and tariff rules (Customs & tariff). The vs-other-loco numbers are agent-supplied indicative premia, not live quotes.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Page loads contracts and prior loco analyses in parallel',
        detail:
          'Two GETs: /api/contractiq/contracts and /api/contractiq/metals/loco. The browser joins them by contract_id.',
      },
      {
        step: 2,
        label: 'User clicks Analyze on a contract',
        detail:
          'POST /api/contractiq/metals/contracts/{id}/loco-analyze. The router invokes the AgentForge SDK against contractiq-metals-loco-analyzer.',
      },
      {
        step: 3,
        label: 'Agent runs database_query, web_search and knowledge_search',
        detail:
          'The analyzer loads contract and metals extraction via database_query, fetches current loco-premium reference levels via web_search, and pulls the customs and tariff section for the loco from the knowledge base via knowledge_search.',
      },
      {
        step: 4,
        label: 'API persists the envelope',
        detail:
          'The structured result (loco, reference_price_usd_per_oz, loco_premium_pct, loco_premium_usd_per_oz, comparison, insurance, customs_tariff, chain_of_integrity, repatriation, vault_handover, alerts, recommendations) is written into the metals_loco table.',
      },
      {
        step: 5,
        label: 'UI reloads and re-renders',
        detail:
          'Browser calls load() again. The expand panel reads directly from the saved envelope.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'guardrail']),
      {
        term: 'Loco swap',
        definition:
          'A trade that moves a metal balance from one loco to another (typically London to Zurich or vice versa) without physically shipping bars. The two parties net off offsetting positions on each other\'s books and settle the loco premium difference in cash.',
      },
      {
        term: 'Loco premium',
        definition:
          'The price uplift or discount for delivery at a vault other than London. Loco-Zurich and loco-Shanghai usually trade over loco-London because of demand-side or customs frictions. Quoted in basis points of price or in USD per ounce.',
      },
      {
        term: 'Chain of integrity',
        definition:
          'The unbroken sequence of custody for a bar from refiner stamp through every vault handover to the current holder. LBMA Good Delivery bars retain integrity only while they sit in approved vaults and move under approved logistics. Breaking the chain forces a fresh assay.',
      },
      {
        term: 'Vault handover',
        definition:
          'The procedure that transfers ownership of a specific allocated bar (or an unallocated balance) from one party to another inside the same vault. Usually settled through a credit advice and a stocklist update, with no physical movement.',
      },
      {
        term: 'Repatriation',
        definition:
          'The right to call your metal out of the vault and ship it elsewhere — to your own warehouse or a different loco. Many institutional contracts require advance notice and put the shipping and re-assay costs on the holder.',
      },
      {
        term: 'Customs and tariff',
        definition:
          'The import duty, VAT treatment and inspection regime at the loco. London and Zurich treat investment-grade bullion as VAT-exempt under specific HS codes, while semi-fabricated metal and jewelry-grade bars face full tariffs.',
      },
    ],
  },

  'metals-refiners': {
    routeKey: 'metals-refiners',
    page_title: 'Refiner Watch',
    purpose:
      'Counterparty monitor for the refiners named in your portfolio. The refiner watch agent reads every refiner mentioned in any of your metals contracts and then checks the current LBMA gold and silver Good Delivery Lists, the LPPM platinum and palladium lists, the OFAC SDN list, and the public audit-finding history for each one. A row is shown per refiner with its status on each list, OFAC flag, next audit date and the count of contracts in your portfolio that name it.\n\nWhen a refiner\'s status has changed since the previous scan, the scan publishes an alert at the top of the page (refiner, list affected, previous status, current status, effective date) with a recommended action. The watch does not act on the alert — it surfaces it so legal and trading can decide.',
    sections: [
      {
        title: 'Page header + Run scan button',
        what_it_shows:
          'Page title and the Run scan button. Clicking the button POSTs to /api/contractiq/metals/refiner-watch/scan, which dispatches the refiner watch agent and writes any status changes into the alerts list.',
        agent_slug: 'contractiq-metals-refiner-watch',
        tools_used: ['database_query', 'web_search', 'knowledge_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'The scan rebuilds the refiner roster from your contracts via database_query, fetches the active LBMA and LPPM lists via web_search, and pulls historical audit notes from the knowledge base via knowledge_search. The summary line returned by the agent is shown in the toast.',
      },
      {
        title: 'Alerts banner',
        what_it_shows:
          'A red card for each refiner whose status changed since the last scan, with the refiner name, the alert kind, the affected list, the previous and current status, the effective date, and a recommended action.',
        agent_slug: 'contractiq-metals-refiner-watch',
        tools_used: ['web_search', 'knowledge_search'],
        data_quality: 'mixed',
        layman_note:
          'The previous-vs-current status comparison is computed by the agent against the prior scan. The recommended action is an LLM suggestion — treat it as a starting point for legal review, not a settled instruction.',
      },
      {
        title: 'Refiners table',
        what_it_shows:
          'One row per refiner with LBMA Gold, LBMA Silver, LPPM Pt and LPPM Pd status pills (active, suspended, delisted, not_listed or unknown), an OFAC SDN column (listed or clean), the next audit date and the count of contracts in your portfolio that name the refiner.',
        agent_slug: 'contractiq-metals-refiner-watch',
        tools_used: ['database_query', 'web_search'],
        data_quality: 'real-fetched',
        layman_note:
          'The status fields come from the LBMA and LPPM published lists fetched at scan time. The OFAC flag comes from a sanctions search. The contract count is a real count in the tenant\'s database.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Page loads the current refiner roster',
        detail:
          'GET /api/contractiq/metals/refiner-watch returns the saved roster rows for the tenant, including the last alert and last_scanned_at on each refiner.',
      },
      {
        step: 2,
        label: 'User clicks Run scan',
        detail:
          'POST /api/contractiq/metals/refiner-watch/scan. The router invokes the AgentForge SDK against contractiq-metals-refiner-watch.',
      },
      {
        step: 3,
        label: 'Agent runs database_query, web_search and knowledge_search',
        detail:
          'The watch pulls every refiner named in the tenant\'s metals tables via database_query, fetches the current LBMA gold and silver Good Delivery Lists and the LPPM platinum and palladium lists via web_search, then checks historical audit notes from the metals knowledge base via knowledge_search.',
      },
      {
        step: 4,
        label: 'API persists the roster and any alerts',
        detail:
          'Each refiner row in the metals_refiner_watch table is upserted with the latest status, the latest audit date and the latest alert. Alerts are returned in the response so the UI can render the red banner.',
      },
      {
        step: 5,
        label: 'UI shows alerts and refreshes the table',
        detail:
          'Browser shows the alerts list at the top and calls load() to refresh the table. No client-side computation on the row data.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'agent', 'pipeline', 'guardrail']),
      {
        term: 'LBMA',
        definition:
          'London Bullion Market Association. Publishes the Good Delivery List for gold and silver refiners and runs the Responsible Gold Guidance audit programme that determines whether a refiner stays on the list.',
      },
      {
        term: 'LPPM',
        definition:
          'London Platinum and Palladium Market. Publishes the Good Delivery List for platinum and palladium refiners. Status mirrors the LBMA convention (active, suspended, delisted).',
      },
      {
        term: 'Good Delivery List',
        definition:
          'The published roster of refiners whose bars are accepted at face value by the London wholesale market. A refiner can move between active, suspended, delisted and never-listed states. Each move is an event this page surfaces as an alert.',
      },
      {
        term: 'OFAC SDN',
        definition:
          'The US Treasury Office of Foreign Assets Control list of Specially Designated Nationals. A refiner appearing on the SDN list cannot lawfully transact with US persons, which materially changes contract enforceability and payment routing.',
      },
      {
        term: 'Refining hallmark',
        definition:
          'The stamp a refiner places on each bar it produces — its registered mark, the bar serial number, the assay year. LBMA-recognised hallmarks let the bar move through London vaults without re-assay. If the refiner is delisted, future bars lose that recognition.',
      },
      {
        term: 'Audit finding',
        definition:
          'A documented gap or non-conformance raised against a refiner during the LBMA RGG (or LPPM) annual audit. A "material" finding can trigger suspension. Findings drive the next_audit_date the watch tracks.',
      },
    ],
  },

  'metals-sourcing': {
    routeKey: 'metals-sourcing',
    page_title: 'Responsible Sourcing',
    purpose:
      'Per-contract responsible-sourcing audit. The sourcing tracker reads the contract and the metals extraction, identifies the origin country, the mine and the refiner, and walks through the OECD five-step due diligence and the LBMA Responsible Gold Guidance step-by-step evidence. It then audits RJC chain of custody, checks whether the Doré Integrity protocol is applicable, flags high-risk origins (DRC, CAR, Sudan, Eritrea, Russia post-Feb 2022 without an explicit exclusion clause), and lists gaps with a remediation suggestion per gap.\n\nThe audit-readiness score is a 0..1 model summary of the gap count and the evidence found. It is meant for triage before an internal audit, not as the audit itself. The transport route, the OECD evidence tiles and the LBMA RGG evidence tiles are the auditable detail.',
    sections: [
      {
        title: 'Page header + contract list',
        what_it_shows:
          'One row per contract with title, counterparty, then once audited the origin country with a risk-class chip (low / medium / high), the audit-readiness score, and the gaps count.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Rows come from contracts and metals-sourcing tables. The origin and readiness only show after the tracker has been run on that contract.',
      },
      {
        title: 'Audit / Re-audit action',
        what_it_shows:
          'Posts to /api/contractiq/metals/contracts/{id}/sourcing-audit. That endpoint dispatches the sourcing tracker agent and persists the result envelope.',
        agent_slug: 'contractiq-metals-sourcing-tracker',
        tools_used: ['database_query', 'knowledge_search', 'web_search'],
        data_quality: 'agent-simulated',
        layman_note:
          'The tracker reads contract, metals extraction and counterparty rows via database_query, pulls published guidance and audit findings from the knowledge base via knowledge_search, and checks country-of-origin sanctions and mine identity via web_search.',
      },
      {
        title: 'Detail panel — Route, OECD 5-step due diligence, LBMA Responsible Gold Guidance evidence, Gaps',
        what_it_shows:
          'Expanding a row shows the transport route as a sequence of locations, then a row of five evidence tiles for the OECD due-diligence steps (each tile shows the step name, a present/missing icon and the citation), then a row of evidence tiles for the LBMA RGG steps, then a Gaps block listing each item with its remediation.',
        agent_slug: 'contractiq-metals-sourcing-tracker',
        tools_used: ['database_query', 'knowledge_search'],
        data_quality: 'mixed',
        layman_note:
          'The "present" flag on each evidence tile is the agent\'s judgement against the contract text and any uploaded supporting documents. The citation under the tile points to where that evidence was found. The remediation suggestion is LLM-generated — keep it as a starting point for the team that owns supplier onboarding.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Page loads contracts and prior sourcing audits in parallel',
        detail:
          'Two GETs: /api/contractiq/contracts and /api/contractiq/metals/sourcing. The browser joins them by contract_id.',
      },
      {
        step: 2,
        label: 'User clicks Audit on a contract',
        detail:
          'POST /api/contractiq/metals/contracts/{id}/sourcing-audit. The router invokes the AgentForge SDK against contractiq-metals-sourcing-tracker.',
      },
      {
        step: 3,
        label: 'Agent runs database_query, knowledge_search and web_search',
        detail:
          'The tracker loads contract, metals extraction and counterparty rows via database_query, pulls OECD DDG, LBMA RGG, RJC chain-of-custody and Doré Integrity protocol guidance from the knowledge base via knowledge_search, and checks the sanctions status of the country of origin and the mine identity via web_search.',
      },
      {
        step: 4,
        label: 'API persists the envelope',
        detail:
          'The structured result (origin_country, origin_risk_class, mine_disclosed, refiner_disclosed, refiner_lbma_status, transport_route, oecd_5_step_evidence, lbma_rgg_step_evidence, rjc_chain_of_custody, gaps, audit_readiness_score) is written into the metals_sourcing table.',
      },
      {
        step: 5,
        label: 'UI reloads and re-renders',
        detail:
          'Browser calls load(). The detail panel renders directly from the saved envelope. Tile colour comes from the evidence_present flag, citation text comes from the agent.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'guardrail', 'counterparty']),
      {
        term: 'OECD Due Diligence Guidance',
        definition:
          'The OECD five-step framework for responsible mineral supply chains. Step 1 establishes a management system, step 2 identifies and assesses risk, step 3 designs a risk-response strategy, step 4 commissions a third-party audit at identified choke points, step 5 reports publicly. Each step has its own evidence tile on this page.',
      },
      {
        term: 'LBMA Responsible Gold Guidance',
        definition:
          'The LBMA standard that operationalises the OECD framework for gold refiners. It mirrors the five OECD steps but adds specific requirements around KYC of mine sources, chain of custody, and an annual independent assurance report. Active Good Delivery refiners must pass it every year.',
      },
      {
        term: 'RJC chain of custody',
        definition:
          'Responsible Jewellery Council Chain of Custody standard. Tracks gold, silver and platinum-group metals from a certified source through every processing step until final product. Each tier of the supply chain has to be RJC-certified for the chain to remain unbroken.',
      },
      {
        term: 'Doré Integrity protocol',
        definition:
          'The LBMA 2020 protocol that defines how doré (impure mine-output gold-silver bars) is sampled, assayed, declared and tracked from mine gate through to refinery intake. Designed to prevent doré from being a back door for non-conformant material into Good Delivery refining.',
      },
      {
        term: 'High-risk origin',
        definition:
          'Country of origin flagged by the OECD or the EU 2017/821 list as conflict-affected or high-risk for mineral supply. DRC, Central African Republic, Sudan and Eritrea are routinely listed. Russia is treated as high-risk post-Feb 2022 unless the contract explicitly excludes Russian-origin metal.',
      },
      {
        term: 'Artisanal small-scale mining (ASM)',
        definition:
          'Informal, low-capital mining performed by independent miners and small cooperatives. ASM is a major source of gold globally but carries elevated human-rights, environmental and origin-traceability risk. RJC publishes a specific ASM Standard that contracts should reference if ASM is in scope.',
      },
      {
        term: 'Audit readiness',
        definition:
          'A 0..1 score the tracker assigns based on the number and severity of evidence gaps it found. A score above 0.85 means most evidence is present and citations check out, between 0.6 and 0.85 means notable gaps, below 0.6 means the contract is not ready for an external audit until the gaps are closed.',
      },
    ],
  },

  clauses: {
    routeKey: 'clauses',
    page_title: 'Clause library and gap heatmap',
    purpose:
      'Every clause the extractor has already lifted out of your uploaded contracts, indexed in one place. You can search by keyword, filter by clause type or risk level, click any row to see the full clause text, and jump back to the parent contract.\n\nThe Gaps tab flips the perspective. Instead of listing clauses you have, it lists the clauses you are missing. The platform keeps a fixed taxonomy of standard clause types (payment, termination, indemnity, liability, force majeure, change of law, and so on). For each contract, the heatmap shows which standard types were found and which are absent. The coverage roll-up tells you which clause types are systematically underrepresented across your book.\n\nNothing on this page runs an agent on load. The clauses you see were produced by the contractiq-extractor agent at the time each contract was ingested. The Gaps view is a deterministic SQL join against the same stored rows.',
    sections: [
      {
        title: 'Library',
        what_it_shows:
          'The full list of extracted clauses across every contract in your portfolio. Each row shows the clause number, type, risk level, title, and the contract it came from. Filters narrow by type or risk and the search box matches against title, text, and number. Clicking a row expands the full clause text plus risk notes.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These rows are written to the clauses table at ingest time. The risk level on each row is whatever the contractiq-extractor agent wrote when the contract was uploaded. If you want a fresh assessment, re-extract the contract from its detail page.',
      },
      {
        title: 'Gaps',
        what_it_shows:
          'Two views built from the same source. Coverage by clause type shows, per standard clause category, what percentage of your contracts have at least one clause of that type. The per-contract gap heatmap is a matrix where rows are contracts, columns are standard clause types, and each cell is green (present, with a count) or red (missing).',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'A red cell does not mean the contract is wrong. It means the extractor did not find a clause of that type. The fix when you spot a real gap is to negotiate the missing clause in the next renewal. The fix when you spot a false gap is to re-extract the contract because the text is in there and the extractor missed it.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/clauses and /api/contractiq/clauses/gaps in parallel',
        detail:
          'Two GET requests. The first carries the search and filter query string, capped at 200 rows. The second returns the standard taxonomy plus per-contract present/missing rows. Both are scoped to the calling tenant by the user token.',
      },
      {
        step: 2,
        label: 'API runs SQL against the clauses and contracts tables',
        detail:
          'No agent is involved. The library endpoint selects clauses with optional WHERE filters. The gaps endpoint joins contracts against the taxonomy and counts what each contract has by type.',
      },
      {
        step: 3,
        label: 'UI renders the library list or the heatmap grid',
        detail:
          'Tab state lives in the browser. Expanding a clause toggles a Set in component state. No further math beyond formatting.',
      },
    ],
    glossary: [
      ...pick(['clause_taxonomy', 'anomaly_score']),
      {
        term: 'Gap heatmap',
        definition:
          'A matrix where each cell shows whether a contract has at least one clause of a given standard type. Green means present, red means missing. The colour does not score risk — it only records presence.',
      },
      {
        term: 'Coverage percentage',
        definition:
          'For a given clause type, the share of contracts in your portfolio that have at least one clause of that type. 75% means three out of four of your contracts have it. Low coverage is a signal to check whether the missing clauses are real exposures or extraction misses.',
      },
      {
        term: 'Risk level',
        definition:
          'A four-band label (low, medium, high, critical) the extractor wrote when the clause was first parsed. It reflects the language of the clause, not the dollar exposure. A critical-rated indemnity in a small contract still carries less money risk than a medium-rated indemnity in a much larger one.',
      },
    ],
  },

  compare: {
    routeKey: 'compare',
    page_title: 'Contract comparison',
    purpose:
      'A three-step wizard for putting two to five of your contracts side by side. Step one picks the contracts from the analyzed set. Step two picks one of three comparison lenses: a side-by-side field table, a risk-category radar, or a financial roll-up. Step three renders the selected view from data already on file.\n\nNo agent fires from this page. The lists, the radar, and the financial tiles are all built from rows the extractor wrote when each contract was first ingested. Comparing two contracts therefore returns the same answer every time until one of the underlying contracts is re-extracted.',
    sections: [
      {
        title: 'Select contracts (step 1)',
        what_it_shows:
          'The grid of every analyzed contract in your portfolio with title, type, counterparty, capacity and risk score. You pick two to five and continue.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Only contracts in analyzed status appear here. Contracts that are still extracting or that failed extraction are hidden so the comparison has something to compare.',
      },
      {
        title: 'Side-by-side',
        what_it_shows:
          'A field-by-field table covering type, counterparty, capacity, value, risk score, effective and expiry dates, plus a count of clauses and assets. Two bar charts compare capacity (MW) and risk score across the picked contracts.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Every cell here is a direct read from the contracts table. A dash means the field was not extracted for that contract, not that the contract has a zero value.',
      },
      {
        title: 'Risk matrix',
        what_it_shows:
          'An overlaid radar across the six risk categories (market, credit, operational, regulatory, legal, technology), one ring per contract. Below the radar, a grouped bar chart shows the same scores by category.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The category scores come from the risk_analyses rows the contractiq-extractor agent wrote at ingest. The overlay is geometry, not a fresh model run. If a category is missing for a contract, that ring stays at zero on that axis.',
      },
      {
        title: 'Financial',
        what_it_shows:
          'Three roll-up tiles (total capacity in MW, total contract value, average risk score) above bar charts for contract value and capacity. A commercial terms table lines up extracted commercial fields across the picked contracts so divergences are visible at a glance.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The roll-ups are simple sums and averages over the picked contracts. The commercial terms table only shows fields the extractor tagged as section = commercial_terms. Anything not parsed at that section level will be missing here.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/contracts to populate the picker',
        detail:
          'A single GET with sort=newest and limit=100. The picker only displays rows with status = analyzed.',
      },
      {
        step: 2,
        label: 'On Compare, browser fetches /api/contractiq/contracts/{id} for each picked contract',
        detail:
          'One GET per selected contract id, run in parallel. Each response is a full detail object including clauses, risk_analyses, assets and extracted_data. The page caches them in a details map keyed by contract id.',
      },
      {
        step: 3,
        label: 'UI renders the selected view from the cached details',
        detail:
          'No agent is invoked. The radar, bar charts and tables are computed in the browser from the cached objects.',
      },
    ],
    glossary: [
      ...pick(['ppa', 'counterparty', 'mtm']),
      {
        term: 'Side-by-side comparison',
        definition:
          'A view that lines up the same fields across two or more contracts so divergences are visible without flipping between pages. Used for renewals, where the new draft needs to be checked against the live contract.',
      },
      {
        term: 'Commercial terms',
        definition:
          'The set of fields the extractor tags as section = commercial_terms — typically price, indexation, volume, payment timing, and similar. The financial view of the comparison only pulls fields from this section.',
      },
    ],
  },

  'deal-clusters': {
    routeKey: 'deal-clusters',
    page_title: 'Deal clusters and ETRM extraction pipeline',
    purpose:
      'A portfolio-wide view of how every contract decomposes into deal clusters that an ETRM system (Endur, Allegro, Openlink) can consume. The platform takes each contract, groups its clauses into deal clusters (Power Physical, Power Swap, Certificate Physical, Gas Physical, Fee/Cash), turns each cluster into typed deal legs, and matches each cluster to an uploaded JSON template. The page lays that whole chain out as a DAG per contract.\n\nThe deal clusters and legs are produced at extraction time. The ETRM Deal-Type Matrix is a fixed reference card built into the page (12 hard-coded rules). The Endur JSON Templates panel lets operators upload skeleton templates that the contractiq-endur-template-filler agent populates from any cluster on demand.',
    sections: [
      {
        title: 'ETRM Deal-Type Matrix',
        what_it_shows:
          'A 12-row reference table mapping commodity x delivery x optionality x cashflow to the ETRM deal type each cluster should land in. Static content, expanded by default.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Nothing model-generated here. This is a hard-coded crosswalk you can use to sanity check what the cluster classifier decided.',
      },
      {
        title: 'Endur JSON Templates',
        what_it_shows:
          'The list of JSON skeleton templates uploaded for each ETRM deal-type category, plus an Upload template control and a Generate Endur JSON for a cluster picker. Hitting Generate runs the agent that fills the template using a specific cluster as input.',
        agent_slug: 'contractiq-endur-template-filler',
        tools_used: ['structured_extractor', 'llm_call'],
        data_quality: 'agent-simulated',
        layman_note:
          'The generated payload is the agent reading a clusters clauses and legs and writing values into the placeholder slots of the chosen template. The output is auditable JSON. Empty placeholders are left as null rather than being invented.',
      },
      {
        title: 'Extraction Pipeline DAG',
        what_it_shows:
          'Per contract, a four-column DAG: Contract -> Deal Clusters -> Deal Legs -> Endur Templates. Each cluster carries its clause count, each leg shows its field count, and each template node shows whether it is a starter or a custom upload. Hovering highlights the upstream and downstream path.',
        agent_slug: 'contractiq-extractor',
        tools_used: ['document_parser', 'structured_extractor'],
        data_quality: 'real-fetched',
        layman_note:
          'The clusters and legs are not generated when you open this page. They were written by the extractor when the contract was uploaded. The DAG is a layout over already-persisted rows.',
      },
      {
        title: 'Per-contract KPI strip',
        what_it_shows:
          'Five tiles above the DAG: contracts in view, total deal clusters, distinct cluster types, total deal legs, distinct counterparties. Reflects the current filter.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Pure aggregates. Each tile is a count over the filtered cluster rows already loaded into the page.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/deal-clusters and /api/contractiq/templates in parallel',
        detail:
          'The deal-clusters endpoint returns every cluster across the tenants contracts with its clauses, clause_rows, and deal_legs. The templates endpoint returns the uploaded JSON skeletons grouped by category.',
      },
      {
        step: 2,
        label: 'UI groups the clusters by contract and renders one DAG per group',
        detail:
          'The grouping, the legend, the highlight-on-hover graph traversal, and the SVG edges between nodes are all browser-side. No agent is invoked at this stage.',
      },
      {
        step: 3,
        label: 'On Generate Endur JSON, the API runs contractiq-endur-template-filler',
        detail:
          'A POST to /api/contractiq/generate-endur-json sends the cluster id and template id. The agent reads the clusters clauses and legs and fills the template placeholders with structured output. The resulting JSON is returned to the modal for download.',
      },
    ],
    glossary: [
      ...pick(['agent', 'pipeline', 'guardrail']),
      {
        term: 'Deal cluster (DBSCAN)',
        definition:
          'A group of clauses that together describe one tradable economic position inside a contract. The platforms taxonomy is fixed (Power Physical, Power Swap, Certificate Physical, Gas Physical, Fee/Cash) and each cluster maps to an ETRM deal type. The grouping rule is rule-based at extraction time, not learned per tenant.',
      },
      {
        term: 'Deal leg',
        definition:
          'The structured object an ETRM system expects per side of a trade. A Power Swap cluster turns into two legs: a Rec Fixed leg and a Pay Float leg. Each leg carries the fields (notional, index, frequency, currency) the ETRM system needs to book the position.',
      },
      {
        term: 'Endur deal template',
        definition:
          'A JSON skeleton with placeholder tokens that an ETRM (Endur) team uploads once per deal type. The contractiq-endur-template-filler agent later populates the placeholders from a specific cluster so the resulting payload can be pasted straight into Endur.',
      },
      {
        term: 'ISDA master agreement',
        definition:
          'The standardised umbrella contract published by the International Swaps and Derivatives Association that governs many bilateral derivatives. Individual trades sit underneath the ISDA master as confirmations. Relevant here because Power Swap and Gas Swap clusters often reference an ISDA master in their termination and netting clauses.',
      },
    ],
  },

  features: {
    routeKey: 'features',
    page_title: 'Capabilities catalogue',
    purpose:
      'A long-form tour of every module in ContractIQ, grouped into six sections: Foundation, Daily Operations, Risk and Compliance, Portfolio Intelligence, Markets and Insight, and Precious Metals. For each module the page names the agent that backs it, what goes in, what comes out, and the steps it runs. The intent is to make it cheap for a new user to see what the platform can do without clicking into every page first.\n\nNothing on this page runs at load. The content is statically authored in the page component itself. The agent slugs listed against each module are real agents that exist in the Abenix seed data and that the corresponding page actually invokes.',
    sections: [
      {
        title: 'Five pillars',
        what_it_shows:
          'Five short tiles at the top: every interesting calculation is an agent, every answer is cited, everything is portfolio-aware, every run is observable, live updates over SSE. These are the platforms design principles, not module descriptions.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Static text. Use this as the orientation card before you go into the section catalogue below.',
      },
      {
        title: 'Foundation modules',
        what_it_shows:
          'Four core primitives every other module depends on: Contract Upload, Standard Extraction, Deep Extraction, and the Clause Library plus Gap Heatmap. Each card names its agent, the file the agent lives in, and the typical inputs and outputs.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Click open on any card to jump to that module. The agent name shown is the slug you can search for in the Abenix admin to see the actual prompt and tool list.',
      },
      {
        title: 'Daily Operations modules',
        what_it_shows:
          'Four modules used in the morning routine: Daily Briefing, Renewals Copilot, Force Majeure Monitor, Settlement Reconciliation. Each carries citation back to the relevant external standard where applicable (ICC FM clause 2020, UNIDROIT 7.1.7, and so on).',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'These are the modules a contracts team would open every morning. The standards listed are real standards the agents are configured to reference in their prompts.',
      },
      {
        title: 'Risk and Compliance modules',
        what_it_shows:
          'Five risk modules: Clause Anomaly Detector, Stress Test Simulator, Hedge Idea Generator, Counterparty Risk, and KYC Standard Checks. The KYC card lists the regulatory frameworks the agent is configured against (FATF 40, EU AMLD6, OFAC SDN).',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'The KYC standards line is not marketing. The agents prompt instructs it to source the lists named there. If your jurisdiction needs a different list, those agents are where to extend.',
      },
      {
        title: 'Portfolio Intelligence, Markets and Insight, Precious Metals sections',
        what_it_shows:
          'The remaining catalogue: portfolio-level modules (Deal Clusters, Contract Families, Portfolio Valuation, Clause Benchmarks), market and insight modules (Market and Risk, Simulations, Event Timeline, Version Diff, Compare, Contract Chat), and the six dedicated metals modules (Extraction, Compliance Audit, Dispute Risk, Loco, Sourcing, Refiner Watch).',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Each card is a link into the module. Use this page when you are pitching internal stakeholders and need a single map of what the platform does.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Static page render',
        detail:
          'The page is a plain client component. There is no fetch, no agent call, no SSE stream when it loads. The content is in the source file itself.',
      },
      {
        step: 2,
        label: 'Click-through into a module',
        detail:
          'Each module card has an open link. Clicking it navigates to the actual page (for example [/insights/briefing](/insights/briefing) or [/credit-risk/kyc](/credit-risk/kyc)) where the agent does fire.',
      },
    ],
    glossary: [
      ...pick(['agent_atlas', 'model_card', 'agent', 'pipeline', 'agentic_workflow']),
      {
        term: 'Feature catalogue',
        definition:
          'A statically authored summary of every module the product ships. Used as orientation for new users. Not a substitute for the agent atlas, which carries the live model and cost data.',
      },
    ],
  },

  market: {
    routeKey: 'market',
    page_title: 'Market and risk monitor',
    purpose:
      'A live snapshot of where the market is sitting today, what your portfolio is worth at those prices, and which contracts are exposed to the next move. Four indicator tiles at the top (Power DE, Carbon EU ETS, EUR/USD, open Alerts) come from the platforms market-data feeds. Four PnL tiles below them show the portfolios annual PnL, mark-to-market, and counts of contracts that are in or out of the money at current prices.\n\nThe Run Monitor button kicks off the contractiq-market-monitor agent. That agent re-fetches the market feed, recomputes each contracts exposure against its strike, and writes new alert rows for anything that moved more than the configured threshold.',
    sections: [
      {
        title: 'Market indicator tiles',
        what_it_shows:
          'Four headline indicators: Power (DE day-ahead), Carbon (EU ETS), EUR/USD, and unacknowledged alert count. Each tile shows the current value with the source observation count and unit, or a live data unavailable note when the feed did not return data.',
        agent_slug: 'contractiq-market-monitor',
        tools_used: ['market_data', 'entso_e_tool', 'ember_tool', 'ecb_rates_tool'],
        data_quality: 'real-fetched',
        layman_note:
          'These tiles read from rows the most recent monitor run wrote into the market_data cache. They do not call the upstream feed on every page load. When a tile says live data unavailable, the last run could not reach that feed and the tile honestly degrades rather than showing a stale number.',
      },
      {
        title: 'PnL KPI tiles',
        what_it_shows:
          'Four KPI tiles: total annual PnL across the portfolio, total mark-to-market, count of contracts in the money, count out of the money. Computed from the contract strike (the price in your contract) versus the current spot.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'mixed',
        layman_note:
          'The strike on each contract is real (it was extracted from your document). The spot is real (it came from the market_data tile above). The PnL is arithmetic. It is a paper number — nothing has settled and no cash has moved.',
      },
      {
        title: 'Annual PnL and Mark-to-Market charts',
        what_it_shows:
          'Two side-by-side horizontal bar charts. The first ranks contracts by annual PnL with positive bars in green and negative in red. The second ranks by absolute mark-to-market with positive in cyan and negative in amber.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'mixed',
        layman_note:
          'Same data as the KPIs above, just broken out per contract. Contracts with no contract price extracted are dropped from the chart rather than being shown at zero.',
      },
      {
        title: 'Portfolio Exposure Detail table',
        what_it_shows:
          'One row per contract showing type, contract price, spot price, PnL per MWh, annual PnL, MTM and an ITM/OTM status flag. Status colour codes mark which positions are gaining and which are losing at current prices.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'mixed',
        layman_note:
          'The PnL per MWh column is spot minus strike for a buyer, sign-flipped for a seller. The annual PnL multiplies that by the remaining capacity in MWh per year. The MTM discounts the per-year PnL over the remaining tenor.',
      },
      {
        title: 'Market Alerts',
        what_it_shows:
          'The list of alert rows the monitor wrote, severity-colour-coded (red for critical, amber for warning, blue for info). Each alert has a title, description, type tag, optional delta percent, and an acknowledge button.',
        agent_slug: 'contractiq-market-monitor',
        tools_used: ['llm_call', 'market_data'],
        data_quality: 'agent-simulated',
        layman_note:
          'These alerts are the agents narrative summary of moves it found above threshold. The title and description are LLM-written and may paraphrase. Click acknowledge to retire an alert once you have actioned it.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser polls /api/contractiq/market-data every 15 seconds when live mode is on',
        detail:
          'A GET that returns the current market tile values, the per-contract exposure, the portfolio totals, and the recent alerts. The endpoint reads cached rows, it does not re-fetch the upstream feed.',
      },
      {
        step: 2,
        label: 'Run Monitor POSTs to /api/contractiq/insights/market-monitor/run',
        detail:
          'The API invokes the contractiq-market-monitor agent which re-fetches Ember, ENTSO-E, ECB and other configured feeds, recomputes per-contract exposure, and writes any threshold-breaching changes into the alerts table. The response returns cost and duration.',
      },
      {
        step: 3,
        label: 'Acknowledge an alert posts /api/contractiq/alerts/{id}/acknowledge',
        detail:
          'A direct DB write that flips is_acknowledged on the alert row. The UI lowers its opacity. The alert is not deleted so the audit trail is preserved.',
      },
    ],
    glossary: [
      ...pick(['mtm', 'spot_price', 'forward_curve', 'eua', 'ttf', 'jkm', 'basis_risk']),
      {
        term: 'Market data feed',
        definition:
          'An external data source the platform queries for live or recent market prices. ContractIQ wires Ember for grid carbon, ENTSO-E for European power, ECB for FX, plus optional Yahoo and FRED routes. A failed feed degrades the relevant tile to live data unavailable rather than substituting a stale value.',
      },
      {
        term: 'ITM / OTM',
        definition:
          'In the money / out of the money. A buyer contract is ITM when the spot price is above the contract strike (you would rather hold the contract than buy at spot). A seller contract is ITM when spot is below strike. The flag is colour-coded green for ITM and red for OTM in the exposure table.',
      },
      {
        term: 'Annual PnL',
        definition:
          'The expected profit or loss per year if current spot prices held for the next twelve months. It is spot minus strike per unit, times the expected volume for the year. It is an indicative number, not a forecast.',
      },
    ],
  },

  simulations: {
    routeKey: 'simulations',
    page_title: 'Market simulation and stress test',
    purpose:
      'A workbench for running what-if scenarios on a single contract or the whole portfolio. You pick a scope (portfolio or a specific contract), pick a simulation type (Weather Impact, Price Sensitivity, Monte Carlo, Sentiment Impact, or the combined Full Stress Test), set the parameters, and press Run. The platform routes the call to a simulation agent which produces a structured result object that the page then renders as charts and tiles.\n\nEverything you see on the right is generated. Weather Impact pulls a real climate dataset for the chosen location and runs energy-yield arithmetic over it. Price Sensitivity sweeps the contract price up and down. Monte Carlo runs the configured number of iterations with stochastic moves. Sentiment Impact reads pasted news headlines and adjusts risk premiums. Full Stress Test runs all four and combines the answers.',
    sections: [
      {
        title: 'Simulation scope and type pickers',
        what_it_shows:
          'A scope select (portfolio or one of the loaded contracts) and a stack of five simulation-type cards: Weather Impact, Price Sensitivity, Monte Carlo, Sentiment Analysis, Full Stress Test. Selecting a type reveals the matching parameter block below.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The contract list in the scope picker comes straight from the contracts table. Selecting portfolio runs the simulation across every contract returned, not just the analyzed ones.',
      },
      {
        title: 'Parameter panel',
        what_it_shows:
          'Conditional inputs based on the picked simulation. Weather asks for location, period in months, and which weather variables to include. Price asks for variation percent, steps and discount rate. Monte Carlo asks for iteration count and confidence level. Sentiment takes a free-text block of news headlines.',
        agent_slug: undefined,
        tools_used: [],
        data_quality: 'real-fetched',
        layman_note:
          'Defaults are sensible (Northern Europe, 12 months, 1000 iterations, 95% confidence). If you bump iterations to 10000 the call runs slower but the tail percentiles get more stable.',
      },
      {
        title: 'Simulation result panel',
        what_it_shows:
          'Live results rendered from the agents structured output. Histograms for the distribution, tail tables for P5 and P95, a top-pain contract list when the scope was portfolio, plus the run metadata (model, duration, cost, tool calls).',
        agent_slug: 'contractiq-market-simulator',
        tools_used: ['weather_simulator', 'scenario_planner', 'financial_calculator', 'sentiment_analyzer', 'llm_call'],
        data_quality: 'agent-simulated',
        layman_note:
          'Every number on the right was produced by the agent for this run. Two runs with the same parameters will produce close but not identical numbers because Monte Carlo draws are random and the LLM summary varies. Re-run if you want a second opinion. The Full Stress Test calls the contractiq-stress-test agent in addition for the combined view.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/contracts?limit=50 once on mount',
        detail:
          'Populates the scope picker so the user can target either the portfolio or a specific contract id.',
      },
      {
        step: 2,
        label: 'On Run, browser POSTs to /api/contractiq/simulate',
        detail:
          'The body carries simulation_type, contract_id (or null for portfolio), the parameters block, and the parsed news_headlines list. The API forwards the call to the contractiq-market-simulator agent, or the contractiq-stress-test agent for the combined Full Stress Test.',
      },
      {
        step: 3,
        label: 'API streams the agent result back as JSON',
        detail:
          'The agent reads the inputs, fetches weather, runs Monte Carlo, applies sentiment, and returns a structured results object plus metadata (model used, duration, cost, tool calls). The UI parses it and renders the histogram, tail tables, and roll-ups.',
      },
    ],
    glossary: [
      ...pick(['monte_carlo', 'var', 'cvar', 'stress_scenario', 'shap']),
      {
        term: 'Simulation scenario',
        definition:
          'A defined set of inputs (price band, weather window, sentiment shock, confidence level) that the simulator applies to the contract logic. The output is the distribution of outcomes under that scenario. Nothing trades, nothing settles — it is a what-if read against the contract terms already on file.',
      },
      {
        term: 'Tail percentile (P5 / P95)',
        definition:
          'Where a result sits in the simulated distribution. P5 is the worst 5% of outcomes, P95 is the best 5%. The pair tells you the range you should plan for if conditions go badly or well, not the most likely outcome.',
      },
      {
        term: 'Top-pain contract',
        definition:
          'When the scope is the whole portfolio, the contract that drives the worst tail outcome. Useful for picking the one position to hedge first.',
      },
    ],
  },

  timeline: {
    routeKey: 'timeline',
    page_title: 'Event timeline',
    purpose:
      'A single chronological view of every milestone, deadline, review, renewal and termination trigger lifted out of your contracts. The list is sorted by date and grouped by month, with red badges for items already overdue and amber badges for items due in the next 30 days. Filtering by event type or status narrows the view without leaving the page.\n\nNothing on this page runs an agent. The events were written into the events table by the contractiq-extractor agent when each contract was first ingested. The KPI strip and the row list are direct reads from that table.',
    sections: [
      {
        title: 'KPI strip',
        what_it_shows:
          'Five tiles: total events, overdue count, upcoming in 30 days, renewals count, termination triggers count. Computed from the same payload the row list renders.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Pure counts. Overdue is anything with status other than passed whose date is in the past. Upcoming 30 days is anything with a date inside the next 30 days regardless of status.',
      },
      {
        title: 'Filters',
        what_it_shows:
          'A type select (Milestone, Deadline, Review, Renewal, Termination Trigger) and a status select (Upcoming, Passed, Triggered). Filters re-issue the API call rather than slicing client-side, so the KPI counts also update.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'When you clear the filters the page goes back to the full unfiltered list. Filtering does not skip the KPI strip — the tiles reflect whatever filter is active.',
      },
      {
        title: 'Timeline rows grouped by month',
        what_it_shows:
          'A vertical timeline with one row per event. Each row carries the type badge, the formatted date, an overdue or in-N-days chip, the status pill, the event description and the parent contract title. The row links to the contract detail page.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These are the events the extractor was able to parse out of the contract. If a contract has an event you can see in the PDF but it does not show up here, the parser missed the date. The fix is to re-extract the contract from its detail page.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/timeline with optional event_type and status filters',
        detail:
          'A single GET with the user token. Filters become query string params. The API returns events, by_type, by_status, upcoming_30d, overdue and total in one payload.',
      },
      {
        step: 2,
        label: 'API runs SQL over the events table',
        detail:
          'A scoped select joined to contracts so each event carries its parent contract title and counterparty. No agent is involved at request time.',
      },
      {
        step: 3,
        label: 'UI groups by month and renders',
        detail:
          'Grouping is by event_date formatted as month plus year. Overdue and soon chips are computed in the browser from the event_date relative to now.',
      },
    ],
    glossary: [
      ...pick(['agent']),
      {
        term: 'Timeline event',
        definition:
          'A dated item the extractor lifted from a contract: a milestone, a deadline, a review, a renewal window, or a termination trigger. Each event keeps a pointer back to the clause that produced it so you can audit where it came from.',
      },
      {
        term: 'Overdue',
        definition:
          'An event whose date is in the past and whose status is anything other than passed. The badge is red and the day count shows how long it has been outstanding.',
      },
      {
        term: 'Recurring event',
        definition:
          'An event that the extractor flagged as repeating (annual review, quarterly true-up). The timeline shows the next occurrence; older instances will appear in the audit trail of the parent contract but not on this single-row view.',
      },
    ],
  },

  'contracts-detail': {
    routeKey: 'contracts-detail',
    page_title: 'Contract detail',
    purpose:
      'The deep view of a single uploaded contract. Eight tabs cover everything the platform extracted from the document: a headline Overview, the Clauses list, the Assets list, Risk Analysis radar plus per-category scores, the Events timeline, the raw Extracted Data table, the Functional Analysis DAG (the SEE-BV 11-section taxonomy), and a per-contract Chat where you can ask questions grounded in this contract.\n\nThe tabs that just show extracted fields (Overview, Clauses, Assets, Risk Analysis, Events, Extracted Data) do not run an agent on load. They read rows the contractiq-extractor agent wrote when the contract was first uploaded. Re-Extract and Deep Extract buttons in the header re-run those agents. The Functional Analysis tab runs the contractiq-functional-analysis agent on demand. The Chat tab calls the contractiq-chat agent for every message.',
    sections: [
      {
        title: 'Header with Re-Extract, Deep Extract and What-If',
        what_it_shows:
          'Contract title, type pill, status pill, counterparty pair, capacity and date range. The Re-Extract button re-runs the standard extractor with SSE progress events. The Deep Extract button runs the 100+ field deep extractor. The What-If button navigates to the scenario page for this contract.',
        agent_slug: 'contractiq-extractor',
        tools_used: ['document_parser', 'structured_extractor', 'invoke_agent'],
        data_quality: 'mixed',
        layman_note:
          'The header values are static reads. The buttons are how you re-run the extraction agents if you have changed the document or you want fresher numbers. Re-Extract emits a live status stream so you see each step finish.',
      },
      {
        title: 'Overview tab',
        what_it_shows:
          'Extraction summary tiles (fields, clauses, assets, events, risk categories, pages), a Key Terms list of the top 10 extracted fields, and a Risk Profile radar showing the contracts six risk-category scores.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Everything on this tab is a direct read from the contract detail payload. No agent call when the tab is selected.',
      },
      {
        title: 'Clauses tab',
        what_it_shows:
          'A pie chart of clause types and a bar chart of risk-level counts, plus the full list of clauses with title, type pill, risk pill, body and risk notes. Critical and high clauses are bordered in red and orange.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These are the same clauses you would see for this contract in the [clause library](/clauses), filtered to just this document.',
      },
      {
        title: 'Assets tab',
        what_it_shows:
          'A capacity-by-asset bar chart when there are multiple assets, plus an asset card grid with type, capacity, technology, location and commercial-operations date.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Assets are the physical or financial things the contract is about — a wind farm, a metering point, a refinery bar list. If your contract has none, this tab will say no assets extracted.',
      },
      {
        title: 'Risk Analysis tab',
        what_it_shows:
          'The risk spider chart and a horizontal bar chart of the per-category scores (market, credit, operational, regulatory, legal, technology). Below them, per-category cards with the score, a 0..100 bar, a description and any mitigation notes the extractor wrote.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Each category score is a number the contractiq-extractor agent wrote at ingest. To refresh them, hit Re-Extract in the header.',
      },
      {
        title: 'Events tab',
        what_it_shows:
          'A pie chart of event types and the chronological list of events with type, date, status, parent description and a colour-coded left border per type.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Same events that would appear for this contract on the [event timeline](/timeline), here just scoped to one contract.',
      },
      {
        title: 'Extracted Data tab',
        what_it_shows:
          'Every field the extractor wrote into the extracted_data table, grouped by section (commercial_terms, technical, governance, and so on). Each row shows the field name, the field value, and a confidence bar from the extractor.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The confidence bar is the agents self-reported certainty for that field, not an externally verified score. A 90% confidence on a counterparty name is usually trustworthy. A 90% confidence on a regulatory citation should still be checked manually.',
      },
      {
        title: 'Functional Analysis tab',
        what_it_shows:
          'The SEE-BV 11-section taxonomy DAG: electricity, certificate, gas, payment, volumetric, price/market, imbalance, termination, credit and collateral, force majeure, constraint, plus per-clause events. The clause DAG is drawn left to right by section, edges show data flow between rules, and clicking a node opens a detail modal with a sub-DAG of the events that node generates.',
        agent_slug: 'contractiq-functional-analysis',
        tools_used: ['structured_extractor', 'llm_call'],
        data_quality: 'agent-simulated',
        layman_note:
          'The first time you open this tab the agent has not run yet. Click Run Functional Analysis to fire it. The agent reads the contract end-to-end and writes the 11-section breakdown plus the contract event graph. Re-runs will produce slightly different graphs because the LLMs choices over how to group clauses are not deterministic.',
      },
      {
        title: 'Chat tab',
        what_it_shows:
          'A per-contract chat panel scoped to this document. Each message is prefixed with the contract title so the model has the context. Responses come from the contractiq-chat agent which can call the other modules as tools.',
        agent_slug: 'contractiq-chat',
        tools_used: ['llm_call', 'invoke_agent', 'database_query'],
        data_quality: 'agent-simulated',
        layman_note:
          'Each turn re-runs the agent. The model has access to the rest of the platform through invoke_agent so a question like what is the renewal window can land back at the renewals copilot. Two identical questions can produce different phrasings.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser calls /api/contractiq/contracts/{id} on mount',
        detail:
          'A single GET returning the full detail object: header fields, clauses, assets, risk_analyses, events, extracted_data, extraction_summary. No agent is invoked at this stage.',
      },
      {
        step: 2,
        label: 'Re-Extract and Deep Extract open streaming SSE endpoints',
        detail:
          'A POST to /api/contractiq/contracts/{id}/extract or /deep-extract returns a server-sent event stream. The header status banner shows each agent step transitioning until done, then the page re-fetches the contract.',
      },
      {
        step: 3,
        label: 'Functional Analysis tab POSTs to /api/contractiq/contracts/{id}/functional-analysis on demand',
        detail:
          'The first time the tab is opened (and on each Run click) the API invokes the contractiq-functional-analysis agent. The agent emits the 11-section taxonomy plus the events graph as structured JSON, which the tab renders as a DAG.',
      },
      {
        step: 4,
        label: 'Chat tab POSTs each message to /api/contractiq/chat',
        detail:
          'The browser sends the contract title plus the question. The API forwards to the contractiq-chat agent. Replies are written into the chatMessages state.',
      },
    ],
    glossary: [
      ...pick(['anomaly_score', 'agent', 'pipeline', 'guardrail']),
      {
        term: 'Contract version',
        definition:
          'A specific revision of a contract document. Each time you re-extract or upload an amended copy the platform writes a new version row so the audit trail of what the agent thought at each point is preserved.',
      },
      {
        term: 'Extraction completeness',
        definition:
          'A 0..100 score the extractor writes per contract, equal to the percentage of template sections that came back populated. A score below 60 usually means the source document was a poor scan or a non-standard template that the model could not parse cleanly.',
      },
      {
        term: 'Confidence bar',
        definition:
          'The extractors self-reported certainty for one extracted field. Green above 80%, amber between 50% and 80%, red below 50%. It is a model output, not an external validation.',
      },
      {
        term: 'SEE-BV taxonomy',
        definition:
          'An 11-section breakdown of contract rules used by the functional analysis: electricity delivery, certificate delivery, gas delivery, payment, volumetric and time-series, price and market data, imbalance, termination, credit and collateral, force majeure, constraint. Each section is rendered as a column in the clause DAG.',
      },
    ],
  },

  'credit-risk-counterparty-detail': {
    routeKey: 'credit-risk-counterparty-detail',
    page_title: 'Counterparty detail',
    purpose:
      'A single counterparty drilled down to its financial statements, regulatory permits, and the provenance trail for every number on the page. Use this page to vet a specific trading partner before approving credit exposure or signing a master agreement.\n\nUnlike the parent dashboard which shows the heat map, this page is one-row-deep — every panel here is about THIS counterparty. The Refresh button kicks off the counterparty refresher agent which re-pulls public filings (EDGAR, Companies House, Bundesanzeiger as available) and rebuilds the unified financial view.',
    sections: [
      {
        title: 'Unified financial data',
        what_it_shows:
          'Revenue, EBITDA, net income, total assets, total debt, cash, working capital — normalised to USD millions across the last available reporting periods. Source agencies are named per line.',
        agent_slug: 'ciq-counterparty-refresher',
        tools_used: ['edgar_filings', 'companies_house', 'bundesanzeiger', 'database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'These are filed numbers, not estimates. Each line is normalised from the source filing (10-K, 20-F, annual report) into a common unit. If a line is blank the source either did not report it or the agent could not retrieve it — never a fabricated value.',
      },
      {
        title: 'Derived ratios',
        what_it_shows:
          'Liquidity (current ratio, quick ratio), leverage (debt/equity, debt/EBITDA), profitability (margin, ROA, ROE), and Altman Z-score. All are arithmetic functions of the unified line items above.',
        agent_slug: undefined,
        tools_used: ['financial_calculator'],
        data_quality: 'real-fetched',
        layman_note:
          'No agent runs at this step. The ratios are deterministic — same inputs always give the same outputs. If a ratio reads N/A, it means a denominator was missing in the underlying filing.',
      },
      {
        title: 'Regulatory permits and licenses',
        what_it_shows:
          'Active permits from PHMSA (US pipelines), FERC (US power markets), EPA, and equivalent EU registers. Each row carries the issuing authority, valid-from / valid-to dates, and a link to the source listing.',
        agent_slug: 'ciq-counterparty-refresher',
        tools_used: ['phmsa_lookup', 'epa_echo', 'ferc_elibrary'],
        data_quality: 'real-fetched',
        layman_note:
          'Permits expire. The page sorts by expiry-soon at the top so you spot renewals before they bite. If a permit shows expired and the counterparty is still trading that activity, flag it to compliance.',
      },
      {
        title: 'Provenance trail',
        what_it_shows:
          'For every number on the page, the source URL, the timestamp of the fetch, and the tool that produced it. Click any cell on the financials table to see exactly where that figure came from.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'This is the audit trail. If a regulator asks "where did this number come from?" you can show them the original filing URL with a click. The platform-wide guardrail strips any quoted source that was not actually returned by a tool call.',
      },
      {
        title: 'Refresh button',
        what_it_shows:
          'Triggers a fresh fetch across all the source registries. Typical refresh takes 30-90 seconds and updates the timestamp on every panel that changed.',
        agent_slug: 'ciq-counterparty-refresher',
        tools_used: ['edgar_filings', 'companies_house', 'bundesanzeiger', 'phmsa_lookup', 'epa_echo', 'ferc_elibrary'],
        data_quality: 'real-fetched',
        layman_note:
          'Refresh hits live source APIs. Do not click it on every page load — once per session is enough for vetting. The page caches the previous refresh so you can compare what changed.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Browser GETs three endpoints in parallel',
        detail:
          '/api/contractiq/counterparties/{id}/financials, /permits, and /provenance. All three are DB reads against the counterparty record.',
      },
      {
        step: 2,
        label: 'User clicks Refresh',
        detail:
          'POST /api/contractiq/counterparties/{id}/refresh. The API forwards to the ciq-counterparty-refresher agent via the abenix SDK.',
      },
      {
        step: 3,
        label: 'Agent fans out to public registries',
        detail:
          'edgar_filings for US 10-K, companies_house for UK accounts, bundesanzeiger for German accounts, phmsa_lookup for pipeline permits, epa_echo for environmental compliance, ferc_elibrary for power market participants.',
      },
      {
        step: 4,
        label: 'Agent normalises and writes back',
        detail:
          'Each line item is mapped to the unified schema and written back to the counterparty record. Provenance rows are appended with tool name + source URL + timestamp.',
      },
      {
        step: 5,
        label: 'UI re-fetches the three GET endpoints',
        detail:
          'Same three URLs as step 1. The page renders the new data with the updated timestamps.',
      },
    ],
    glossary: [
      ...pick(['counterparty', 'agent', 'guardrail']),
      { term: 'EDGAR', definition: 'The US SEC public filings database. Source for 10-K (US annual), 20-F (foreign annual), 8-K (current report) — the canonical US disclosure feed.' },
      { term: 'Companies House', definition: 'The UK statutory company register. Annual accounts, charges, directors. Coverage of every UK limited company.' },
      { term: 'Bundesanzeiger', definition: 'The German federal gazette. Mandatory disclosure for German GmbH and AG companies. Often lags 6-12 months behind year-end.' },
      { term: 'Altman Z-score', definition: 'A weighted combination of five accounting ratios that predicts bankruptcy. Below 1.8 means high distress probability; above 3.0 is generally safe.' },
      { term: 'PHMSA', definition: 'US Pipeline and Hazardous Materials Safety Administration. Issues operator certifications for interstate gas and hazardous liquid pipelines.' },
    ],
  },

  'what-if-detail': {
    routeKey: 'what-if-detail',
    page_title: 'What-If Analysis',
    purpose:
      'A scenario perturbation runner that takes one of your contracts and runs it through plausible shocks — price jumps, demand cliffs, force majeure, regulatory changes — to surface how the contract\'s PnL and risk metrics would move. The output is a side-by-side comparison: baseline vs. shocked, with attribution to the specific clauses that drove the change.\n\nThis is not a hedge proposal and not a trade. It is a stress-thinking tool. The scenarios are model output, the contract terms are real.',
    sections: [
      {
        title: 'Scenario picker',
        what_it_shows:
          'A dropdown of named scenarios (price spike, demand cliff, force majeure declaration, regulatory change, counterparty downgrade) plus an option to define a custom shock by editing a parameter set.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'The scenarios themselves are seeded by your tenant admin. Custom shocks are saved per user. Nothing runs until you click Run.',
      },
      {
        title: 'Run analysis button',
        what_it_shows:
          'Fires the what-if analyzer agent on the selected contract + scenario. Typical run is under a minute. The button shows a spinner while the agent is working.',
        agent_slug: 'contractiq-whatif-analyzer',
        tools_used: ['code_asset', 'financial_calculator', 'scenario_planner'],
        data_quality: 'agent-simulated',
        layman_note:
          'The agent reads the contract clauses, applies the scenario shock to each affected term, then recomputes the cashflow. The output is a model estimate — what would happen IF this shock materialised. Nothing in the real world changes.',
      },
      {
        title: 'Baseline vs shocked comparison',
        what_it_shows:
          'Two columns side-by-side: the contract under business-as-usual market conditions, and the contract under the shocked scenario. Each row is a metric (NPV, IRR, peak negative cashflow, breach of covenants) showing the delta.',
        agent_slug: 'contractiq-whatif-analyzer',
        tools_used: ['code_asset'],
        data_quality: 'mixed',
        layman_note:
          'The baseline is real (your contract terms + current market prices). The shocked column is the agent\'s simulation. The delta is the agent\'s estimate of impact — not a guarantee and not a trade signal.',
      },
      {
        title: 'Clause-level attribution',
        what_it_shows:
          'For each scenario, the specific clauses that drove the largest swings. E.g. "Take-or-pay floor at 80% MWh forced an additional $2.4M of fixed cost under the demand cliff scenario."',
        agent_slug: 'contractiq-whatif-analyzer',
        tools_used: ['code_asset'],
        data_quality: 'mixed',
        layman_note:
          'This is the most useful panel for renegotiation. It tells you which clauses are doing the damage so you know what to push back on at the next contract review.',
      },
      {
        title: 'Run history',
        what_it_shows:
          'Every prior what-if run on this contract, with the scenario name, timestamp, and the headline delta. Click any row to view the full output again.',
        agent_slug: undefined,
        tools_used: ['database_query'],
        data_quality: 'real-fetched',
        layman_note:
          'Runs are kept indefinitely so you can show the same analysis at a later meeting without re-running it.',
      },
    ],
    data_flow: [
      {
        step: 1,
        label: 'Page loads three endpoints in parallel',
        detail:
          '/api/contractiq/contracts/{id} for the contract terms, /api/contractiq/whatif/scenarios for the picker, /api/contractiq/whatif/contracts/{id}/runs for the history.',
      },
      {
        step: 2,
        label: 'User picks a scenario and clicks Run',
        detail:
          'POST /api/contractiq/whatif/contracts/{id}/run with the scenario id and optional parameter overrides.',
      },
      {
        step: 3,
        label: 'API forwards to the contractiq-whatif-analyzer agent',
        detail:
          'The router does not compute the shock itself (Wave-2 router thinning). It calls the agent via the abenix SDK with a 10-minute timeout.',
      },
      {
        step: 4,
        label: 'Agent uses code_asset to compute the cashflow delta',
        detail:
          'The actual NPV / IRR / cashflow math lives in a Python code asset called by the agent. Clause-level attribution is computed from the same code asset.',
      },
      {
        step: 5,
        label: 'API writes the run and UI renders the comparison',
        detail:
          'The run lands in the whatif_runs table. The UI shows the baseline-vs-shocked columns plus the clause attribution panel.',
      },
    ],
    glossary: [
      ...pick(['agent', 'guardrail', 'mtm']),
      { term: 'Scenario shock', definition: 'A parameterised perturbation of market or contract inputs (e.g. "gas price up 30% sustained for 12 months"). Scenarios are saved as named templates so the same shock can be reapplied across many contracts.' },
      { term: 'Take-or-pay floor', definition: 'A contract clause obliging the buyer to pay for a minimum volume even if they did not actually take delivery. Common in gas, power, and LNG offtake. The floor becomes a real cash burden under a demand cliff.' },
      { term: 'Clause attribution', definition: 'A decomposition of a P&L delta into the contributing clauses. Tells you which contract terms drove the loss or gain under the scenario.' },
      { term: 'NPV (Net Present Value)', definition: 'The sum of all future cashflows discounted back to today. Positive NPV = the contract makes money on a present-value basis at the chosen discount rate.' },
    ],
  },
};

export function getPageExplanation(routeKey: string): PageExplanation | null {
  return PAGE_EXPLANATIONS[routeKey] ?? null;
}
