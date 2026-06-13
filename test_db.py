import os, hashlib, asyncio, asyncpg
async def main():
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("ABENIX_DATABASE_URL") or os.environ.get("POSTGRES_DSN")
    print("DSN env keys:", [k for k in os.environ if "POSTGRES" in k or "DATABASE" in k or "DB_" in k])
    if not dsn:
        return
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    if "?" in dsn:
        dsn = dsn.split("?", 1)[0]
    conn = await asyncpg.connect(dsn)
    c_hash = hashlib.sha256(b"af_XDj54WZtS5ODpAm9Os1WEOZEKIYPJ2TT7LvDk9sL4NU").hexdigest()
    rust_hash = hashlib.sha256(b"af_UUphFosNXrxzM9y3hVK8BiGTm2Qa2GXh1V_Mnycv8R0").hexdigest()
    cols = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name='api_keys' ORDER BY ordinal_position"
    )
    print("api_keys cols:", [r["column_name"] for r in cols])
    for label, h in [("C", c_hash), ("Rust", rust_hash)]:
        rows = await conn.fetch(
            "SELECT * FROM api_keys WHERE key_hash = $1", h
        )
        print(label, "hash", h[:16], "rows", [dict(r) for r in rows])
    print("--- recent api_keys ---")
    rows = await conn.fetch(
        "SELECT id, name, tenant_id, created_at FROM api_keys ORDER BY created_at DESC LIMIT 20"
    )
    for r in rows:
        print(dict(r))
    await conn.close()
asyncio.run(main())
