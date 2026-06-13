import psycopg2

db_url = "postgresql://abenix:abenix@localhost:5432/abenix"
conn = psycopg2.connect(db_url, connect_timeout=3)
cur = conn.cursor()

print("=== api_keys columns ===")
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name='api_keys' ORDER BY ordinal_position"
)
print([r[0] for r in cur.fetchall()])

print()
print("=== distinct tenant_id in api_keys ===")
cur.execute("SELECT tenant_id, COUNT(*) FROM api_keys GROUP BY tenant_id LIMIT 10")
for r in cur.fetchall():
    print(r)

print()
print("=== Find the audit-2026-06 key by name ===")
cur.execute(
    "SELECT id, tenant_id, user_id, name, tokens_used, cost_used, last_used_at "
    "FROM api_keys WHERE name = 'audit-2026-06' LIMIT 5"
)
for r in cur.fetchall():
    print(r)

print()
print("=== executions columns (look for input/output/payload) ===")
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name='executions' ORDER BY ordinal_position"
)
print([r[0] for r in cur.fetchall()])

print()
print("=== Recent 8 executions cost-split ===")
cur.execute(
    "SELECT id, status, input_tokens, output_tokens, cost, "
    "anthropic_cost, openai_cost, google_cost, other_cost, created_at "
    "FROM executions WHERE created_at > NOW() - INTERVAL '2 hours' "
    "ORDER BY created_at DESC LIMIT 8"
)
for r in cur.fetchall():
    print(r)

print()
print("=== Aggregates across 30d: per-provider vs total cost ===")
cur.execute(
    "SELECT "
    "ROUND(COALESCE(SUM(cost),0)::numeric, 4) as total, "
    "ROUND(COALESCE(SUM(anthropic_cost),0)::numeric, 4) as anth, "
    "ROUND(COALESCE(SUM(openai_cost),0)::numeric, 4) as oai, "
    "ROUND(COALESCE(SUM(google_cost),0)::numeric, 4) as goog, "
    "ROUND(COALESCE(SUM(other_cost),0)::numeric, 4) as other, "
    "COUNT(*) FILTER (WHERE (anthropic_cost+openai_cost+google_cost+other_cost) > 0) AS split_nonzero, "
    "COUNT(*) FILTER (WHERE cost > 0) AS total_nonzero "
    "FROM executions WHERE created_at > NOW() - INTERVAL '30 days'"
)
print(cur.fetchone())

print()
print("=== llm_model_pricing count + sample ===")
cur.execute("SELECT COUNT(*) FROM llm_model_pricing")
print("count:", cur.fetchone())
cur.execute("SELECT model, provider, input_per_m, output_per_m FROM llm_model_pricing LIMIT 5")
for r in cur.fetchall():
    print(r)

print()
print("=== Tenant table cap/quota columns ===")
cur.execute(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name='tenants' ORDER BY ordinal_position"
)
print([r[0] for r in cur.fetchall()])
