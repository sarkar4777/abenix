import httpx, json, sys

# Login fresh each run
r = httpx.post(
    "http://localhost:8001/api/contractiq/auth/login",
    json={"email": "test@contractiq.com", "password": "TestPass123!"},
    timeout=30,
)
tok = r.json()["data"]["access_token"]
print("LOGIN", r.status_code)

q = sys.argv[1] if len(sys.argv) > 1 else "In the gas supply agreement, what is the take-or-pay threshold and what penalty applies if it is breached?"

r = httpx.post(
    "http://localhost:8001/api/contractiq/chat",
    headers={"Authorization": f"Bearer {tok}"},
    json={"query": q},
    timeout=300,
)
print("STATUS", r.status_code)
print(r.text[:4000])
