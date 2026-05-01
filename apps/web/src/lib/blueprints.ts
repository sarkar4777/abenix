/**
 * Abenix Blueprint Definitions — executable use case templates
 * that showcase platform capabilities via the SDK.
 */

export interface Blueprint {
  id: string;
  name: string;
  icon: string;
  description: string;
  agentSlug: string;
  category: string;
  samplePrompt: string;
  features: string[];
  sdkCode: string;
  pythonCode: string;
}

export const BLUEPRINTS: Blueprint[] = [
  {
    id: 'repo-analyzer',
    name: 'GitHub Repository Analyzer',
    icon: 'Code',
    description: 'Deep multi-pass analysis of any GitHub repo: architecture, security (OWASP), code quality, business context. Works with Java, Python, Go, C#, C++, and 20+ languages.',
    agentSlug: 'repo-analyzer',
    category: 'Engineering',
    samplePrompt: 'Analyze the repository structure, identify key entry points, map the architecture, and assess security posture',
    features: ['Pipeline DAG', 'ForEach Parallel', 'GitHub API', 'LLM Analysis', 'Multi-Language'],
    sdkCode: `const forge = new Abenix({ apiKey: 'af_...', baseUrl: API_URL });

// Stream real-time analysis progress
for await (const event of forge.stream('repo-analyzer', prompt)) {
  if (event.type === 'token') output.value += event.text;
  if (event.type === 'tool_call')
    console.log('Tool:', event.name, event.arguments);
  if (event.type === 'done')
    console.log('Cost:', event.cost, 'Confidence:', event.confidence);
}`,
    pythonCode: `client = Abenix(api_key="af_...", base_url=API_URL)

async for event in client.agents.stream("repo-analyzer", prompt):
    if event.type == "token": print(event.text, end="")
    if event.type == "done": print(f"Cost: \${event.cost}")`,
  },
  {
    id: 'financial-ppa',
    name: 'Financial Document Analyzer (PPA)',
    icon: 'DollarSign',
    description: 'Multi-pass extraction from financial documents: structure mapping, table extraction, narrative analysis, cross-validation. LCOE calculations, risk scoring, IRR modeling.',
    agentSlug: 'ppa-contract-analyzer',
    category: 'Finance',
    samplePrompt: 'Analyze this PPA contract: calculate LCOE at different discount rates, assess counterparty risk, model IRR scenarios, and check regulatory compliance',
    features: ['13 Tools', 'Financial Calculator', 'Risk Analyzer', 'Multi-Pass', 'Structured Output'],
    sdkCode: `const result = await forge.execute('ppa-contract-analyzer', prompt, {
  context: {
    contract_text: samplePPAText,
    analysis_scope: ['lcoe', 'risk', 'irr', 'compliance'],
  }
});

console.log('LCOE:', result.output.lcoe_per_mwh);
console.log('Risk Score:', result.output.risk_score);
console.log('IRR:', result.output.irr_scenarios);`,
    pythonCode: `result = await client.agents.execute("ppa-contract-analyzer", prompt,
    context={"contract_text": ppa_text, "analysis_scope": ["lcoe", "risk"]})
print(f"LCOE: \${result.output['lcoe_per_mwh']}/MWh")`,
  },
  {
    id: 'support-triage',
    name: 'Customer Support Triage',
    icon: 'MessageSquare',
    description: 'Automatic ticket classification, priority scoring, sentiment analysis, routing to specialist teams, and draft response generation. Integrates with Zendesk/Jira.',
    agentSlug: 'email-triager',
    category: 'Operations',
    samplePrompt: 'URGENT: Our production API has been returning 500 errors for the last 30 minutes. We are an enterprise customer (CUST-5001) on the Business plan. This is blocking our Q4 release deadline. Please classify severity, route to the right team, and draft a response.',
    features: ['Classification', 'Sentiment Analysis', 'Priority Scoring', 'Conditional Routing', 'Draft Response'],
    sdkCode: `const result = await forge.execute('email-triager', ticketContent, {
  context: {
    customer_tier: 'enterprise',
    customer_id: 'CUST-5001',
    ticket_source: 'email',
  }
});

console.log('Category:', result.output.category);
console.log('Severity:', result.output.severity);
console.log('Priority:', result.output.priority_score);
console.log('Routing:', result.output.routing);`,
    pythonCode: `result = await client.agents.execute("email-triager", ticket,
    context={"customer_tier": "enterprise", "customer_id": "CUST-5001"})
print(f"Route to: {result.output['routing']}")`,
  },
  {
    id: 'energy-risk',
    name: 'Energy Market Risk Analysis',
    icon: 'Zap',
    description: 'Monte Carlo simulation on energy portfolios: VaR calculation, sensitivity analysis, market benchmarking. Uses real-time market data + financial calculator + risk analyzer tools.',
    agentSlug: 'energy-market-analyst',
    category: 'Energy',
    samplePrompt: 'Perform risk analysis on this 150MW solar project portfolio: run Monte Carlo simulation with 10,000 iterations, calculate VaR at 95% confidence, and benchmark against current wholesale energy prices',
    features: ['Risk Analyzer', 'Monte Carlo', 'Financial Calculator', 'Market Data', 'Sensitivity Analysis'],
    sdkCode: `const result = await forge.execute('energy-market-analyst', prompt, {
  context: {
    project_capacity_mw: 150,
    ppa_price_mwh: 45,
    risk_parameters: sampleRiskParams,
    market_data: sampleMarketData,
  }
});

console.log('VaR 95%:', result.output.var_95);
console.log('Expected Return:', result.output.expected_irr);`,
    pythonCode: `result = await client.agents.execute("energy-market-analyst", prompt,
    context={"project_capacity_mw": 150, "ppa_price_mwh": 45})
print(f"VaR 95%: \${result.output['var_95']:,.0f}")`,
  },
  {
    id: 'migration-orchestrator',
    name: 'Data Migration Orchestrator',
    icon: 'Database',
    description: 'Multi-agent pipeline for Exasol-to-BigQuery migration. 7 specialist agents: Schema Architect, SQL Transformer, Data Mover, Validation, Report Migrator, Query Router, Cache Manager.',
    agentSlug: 'migration-orchestrator',
    category: 'Migration',
    samplePrompt: 'Plan the migration of our FINANCE and OPERATIONS schemas from Exasol to BigQuery. Use medallion architecture. Prioritize tables used by MicroStrategy reports.',
    features: ['Agent Step (Sub-Agents)', 'Memory Store/Recall', 'HITL Approval', 'Template Variables', '7-Agent Chain'],
    sdkCode: `for await (const event of forge.stream('migration-orchestrator', prompt, {
  context: {
    source_schemas: 'FINANCE, OPERATIONS',
    target_dataset: 'bronze_layer',
    migration_mode: 'full_load',
  }
})) {
  if (event.type === 'tool_call' && event.name === 'agent_step')
    console.log('Delegating to:', event.arguments.system_prompt?.slice(0, 50));
  if (event.type === 'tool_call' && event.name === 'memory_store')
    console.log('Storing memory:', event.arguments.key);
}`,
    pythonCode: `async for event in client.agents.stream("migration-orchestrator", prompt,
    context={"source_schemas": "FINANCE", "migration_mode": "full_load"}):
    if event.type == "tool_call" and event.name == "memory_store":
        print(f"Memory: {event.arguments['key']}")`,
  },
  {
    id: 'iot-monitoring',
    name: 'IoT Sensor Monitor',
    icon: 'Cpu',
    description: 'Real-time IoT sensor monitoring: ingest telemetry from Redis Streams, detect anomalies via z-score analysis, forecast failures, alert via Slack/email. Supports temperature, pressure, vibration, and custom sensors.',
    agentSlug: 'iot-sensor-monitor',
    category: 'IoT / Manufacturing',
    samplePrompt: 'Monitor the temperature and vibration sensors for equipment PUMP-001. Read the last 100 readings from the telemetry stream, compute baselines, detect any anomalies, and forecast the next 24 hours.',
    features: ['Redis Streams', 'Time-Series Analysis', 'Anomaly Detection', 'Agent Memory', 'Alert Integration'],
    sdkCode: `// Stream IoT sensor analysis in real-time
for await (const event of forge.stream('iot-sensor-monitor', prompt, {
  context: {
    equipment_id: 'PUMP-001',
    sensor_types: ['temperature', 'vibration', 'pressure'],
    alert_threshold: 2.5,
  }
})) {
  if (event.type === 'tool_call' && event.name === 'redis_stream_consumer')
    console.log('Reading sensor data...');
  if (event.type === 'tool_call' && event.name === 'time_series_analyzer')
    console.log('Analyzing trends:', event.arguments.operation);
  if (event.type === 'done')
    console.log('Health Score:', event.data?.health_score);
}`,
    pythonCode: `async for event in client.agents.stream("iot-sensor-monitor", prompt,
    context={"equipment_id": "PUMP-001", "sensor_types": ["temperature", "vibration"]}):
    if event.type == "tool_call" and event.name == "time_series_analyzer":
        print(f"Analyzing: {event.arguments['operation']}")
    if event.type == "done":
        print(f"Anomalies: {event.data.get('anomaly_count', 0)}")`,
  },
  {
    id: 'fraud-detection',
    name: 'Real-Time Fraud Detector',
    icon: 'Shield',
    description: 'Streaming fraud detection: consume transactions from Redis Streams/Kafka, apply rule-based screening + anomaly detection + Monte Carlo risk scoring. Routes high-risk transactions to HITL approval. Maintains per-account behavioral profiles.',
    agentSlug: 'fraud-detector',
    category: 'Finance',
    samplePrompt: 'Analyze the incoming transaction stream for account ACC-12345. Check the last 50 transactions for patterns, compute a fraud risk score, and flag any suspicious activity with specific rule violations.',
    features: ['Event Streaming', 'Risk Scoring', 'HITL Approval', 'Agent Memory', 'Monte Carlo'],
    sdkCode: `// Real-time fraud scoring with HITL gates
for await (const event of forge.stream('fraud-detector', prompt, {
  context: {
    account_id: 'ACC-12345',
    risk_threshold: 70,
    stream_name: 'transactions:incoming',
  }
})) {
  if (event.type === 'tool_call' && event.name === 'risk_analyzer')
    console.log('Risk scoring:', event.arguments);
  if (event.type === 'tool_call' && event.name === 'human_approval')
    console.log('Flagged for review:', event.arguments.action);
  if (event.type === 'done')
    console.log('Decision:', event.data?.decision, 'Score:', event.data?.risk_score);
}`,
    pythonCode: `async for event in client.agents.stream("fraud-detector", prompt,
    context={"account_id": "ACC-12345", "risk_threshold": 70}):
    if event.type == "tool_call" and event.name == "human_approval":
        print(f"FLAGGED: {event.arguments.get('action')}")
    if event.type == "done":
        print(f"Decision: {event.data.get('decision')} (score: {event.data.get('risk_score')})")`,
  },
  {
    id: 'hipaa-processor',
    name: 'HIPAA Document Processor',
    icon: 'FileText',
    description: 'HIPAA-compliant clinical document processing: extracts diagnoses (ICD-10), procedures (CPT), lab results, and medications from medical records. Auto-redacts all PHI/PII before storage. Validates against FHIR R4 schemas.',
    agentSlug: 'hipaa-document-processor',
    category: 'Healthcare',
    samplePrompt: 'Process this patient lab report: extract all test results with reference ranges, identify any critical values, map diagnoses to ICD-10 codes, and generate a FHIR-compliant summary. Ensure all PHI is redacted.',
    features: ['PII Redaction', 'FHIR Validation', 'HITL Approval', 'Structured Extraction', 'Compliance Audit'],
    sdkCode: `// HIPAA-compliant document processing
const result = await forge.execute('hipaa-document-processor', prompt, {
  context: {
    document_url: 's3://medical-docs/lab-report-2025.pdf',
    output_format: 'fhir_r4',
    redaction_strategy: 'mask',
  }
});

console.log('Diagnoses:', result.output.diagnoses);
console.log('PII Redacted:', result.output.pii_detection_count);
console.log('FHIR Valid:', result.output.fhir_validation_passed);`,
    pythonCode: `result = await client.agents.execute("hipaa-document-processor", prompt,
    context={"document_url": "s3://lab-report.pdf", "output_format": "fhir_r4"})
print(f"Diagnoses: {result.output['diagnoses']}")
print(f"PII Redacted: {result.output['pii_detection_count']}")`,
  },
  {
    id: 'financial-pipeline',
    name: 'Financial Analysis Pipeline',
    icon: 'GitBranch',
    description: 'Multi-pass financial document analysis DAG pipeline. Runs structure extraction, table extraction, and narrative analysis in PARALLEL, then cross-validates, scores risk, and generates a compliance-checked report. 6 nodes, 3 parallel branches.',
    agentSlug: 'financial-analysis-pipeline',
    category: 'Finance (Pipeline)',
    samplePrompt: 'Analyze this 10-K filing: extract all financial tables, identify risk factors from the narrative, cross-validate revenue figures across sections, compute risk scores, and generate an executive summary report.',
    features: ['Pipeline DAG', 'Parallel Extraction', 'Cross-Validation', 'Risk Scoring', '6-Node DAG'],
    sdkCode: `// Pipeline streams per-node progress
for await (const event of forge.stream('financial-analysis-pipeline', prompt)) {
  if (event.type === 'node_start') console.log('Starting:', event.node_id);
  if (event.type === 'node_complete') console.log('Done:', event.node_id, event.duration_ms + 'ms');
  if (event.type === 'tool_call') console.log('Tool:', event.name);
  if (event.type === 'done') {
    console.log('Pipeline:', event.pipeline_status);
    console.log('Report:', event.data?.report);
  }
}`,
    pythonCode: `async for event in client.agents.stream("financial-analysis-pipeline", prompt):
    if event.type == "node_start": print(f"Stage: {event.node_id}")
    if event.type == "done": print(f"Status: {event.pipeline_status}")`,
  },
  {
    id: 'support-pipeline',
    name: 'Customer Support Pipeline',
    icon: 'GitBranch',
    description: 'Multi-stage support triage DAG pipeline. Runs classification, sentiment analysis, and customer lookup in PARALLEL, then computes priority score, drafts response, and merges output. Conditional escalation to human review for high-severity tickets.',
    agentSlug: 'customer-support-pipeline',
    category: 'Operations (Pipeline)',
    samplePrompt: 'Triage this support ticket: "Our production API has been returning 500 errors for 30 minutes. Enterprise account CUST-5001, Q4 release blocked." Classify, score priority, analyze sentiment, and draft a response.',
    features: ['Pipeline DAG', 'Parallel Analysis', 'Priority Scoring', 'Conditional Routing', '6-Node DAG'],
    sdkCode: `// Pipeline with context variables for customer info
for await (const event of forge.stream('customer-support-pipeline', prompt, {
  context: {
    customer_id: 'CUST-5001',
    customer_tier: 'enterprise',
    ticket_content: 'Production API 500 errors for 30 minutes',
  }
})) {
  if (event.type === 'node_complete' && event.node_id === 'priority_score')
    console.log('Priority:', JSON.parse(event.output));
  if (event.type === 'node_complete' && event.node_id === 'draft_response')
    console.log('Draft:', event.output);
}`,
    pythonCode: `async for event in client.agents.stream("customer-support-pipeline", prompt,
    context={"customer_id": "CUST-5001", "customer_tier": "enterprise"}):
    if event.type == "node_complete" and event.node_id == "priority_score":
        print(f"Priority: {event.output}")`,
  },
];
