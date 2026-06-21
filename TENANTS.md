# Tenants in Abenix

There are three identity concepts at play in this system. They sit on top of each other but mean different things. This page walks through each layer, what holds it together, and how to add new ones.

## The three identity layers

### Layer one. The platform tenant

The `tenants` table inside Abenix holds one row per customer organisation that pays for the platform. Each row carries an id (uuid), a display name, a plan code, and a created timestamp.

Every platform-side resource (agents, executions, users, code assets, model availability records, knowledge collections) carries a `tenant_id` foreign key pointing back here. Cross-tenant queries are filtered at the router layer so one customer never sees another customer's rows.

On the cluster right now you can see existing tenants by running this query against the database pod.

```bash
kubectl exec abenix-postgresql-0 -n abenix -- \
  sh -c "PGPASSWORD=localpass psql -U postgres -d abenix \
    -c 'SELECT id, name, plan FROM tenants'"
```

### Layer two. The standalone API key

Each standalone application (ContractIQ, Wingman, Industrial IoT, ResolveAI, MidEast Tourism) holds one API key, stored as a row in the `api_keys` table.

A key has three properties that matter here. It belongs to exactly one platform tenant. It carries a delegation scope so it can act on behalf of end users. It is loaded into the standalone pod from a Kubernetes secret at boot time.

At the moment every standalone key in the cluster lives under the single Abenix platform tenant. That tenant becomes the platform-side bucket through which all standalone traffic is counted, rate limited, and billed.

### Layer three. The end user

Each standalone application keeps its own separate user table. ContractIQ has `contractiq_users`. MidEast Tourism has `mideasttourism_users`. ResolveAI follows the same pattern. Wingman has no user table at all and runs as a single hardcoded demo trader. Industrial IoT similarly has no user table.

Standalone ports for reference. ContractIQ runs on 8001, MidEast Tourism on 8002, Industrial IoT on 8003, ResolveAI on 8004, Wingman on 8006.

Each end user row carries its own `tenant_id` column. Importantly, this is not a foreign key into the platform `tenants` table. It is a local scope that the standalone application owns and uses to partition its own data. The values in `contractiq_users.tenant_id` are completely separate from `tenants.id` over in Abenix.

## How one request flows from a browser to the database

Consider a ContractIQ analyst clicking the Run Recommendations button. The flow goes like this.

1. The browser sends a request to ContractIQ with the user's ContractIQ session token.
2. ContractIQ authenticates the token and looks up the analyst row.
3. ContractIQ opens a request to Abenix. It puts its `standalone-contractiq` key in the `X-API-Key` header. It also puts the analyst's identity (subject_id and subject_type) into an `X-Abenix-Subject` header so Abenix can record who actually triggered the call.
4. Abenix authenticates the API key. The key belongs to the Abenix tenant. The key has the `can_delegate` scope, so Abenix accepts the subject header.
5. Abenix creates an `executions` row. The `user_id` column is the key's service account user. The `tenant_id` column is the Abenix tenant. The new `subject_id` and `subject_type` columns are stamped with the analyst's identity.
6. The agent runs on an agent runtime pod. The execution row is updated as the agent progresses.
7. ContractIQ receives the execution id and surfaces it to the browser.
8. The browser polls `/api/contractiq/executions/<id>`. ContractIQ checks that the execution belongs to the analyst by matching on subject_id. The row comes back. The browser renders the result.

The standalone key is best understood as an identity multiplexer. One key, many end users.

## Are all use cases tied to a single seed tenant

Yes, at present. Every standalone API key in the cluster lives under the Abenix platform tenant. From the platform's point of view there is one customer, and that customer routes traffic through several applications. From each standalone application's point of view, it has many end users grouped into its own local tenant scopes.

This was a deliberate choice. The platform handles billing and quota at the platform tenant level. Each standalone application gets to decide its own multi tenancy story. ContractIQ can carry many customer organisations inside `contractiq_users.tenant_id` without changing anything on the platform side.

The cost of this choice is that the Abenix tenant becomes a single chokepoint. Any rate limit applied at the platform tenant level will throttle all standalone usage combined.

## How to create more tenants

There are four ways. Pick the one that matches your goal.

### Way A. Create a platform tenant via the registration endpoint

The fastest way. The registration endpoint creates both a platform tenant and an initial admin user atomically.

```bash
curl -X POST $ABENIX_URL/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@newcustomer.com","password":"<strong>","full_name":"Admin User","tenant_name":"New Customer Corp","plan":"pro"}'
```

`full_name` is required by the register endpoint. `tenant_name` and `plan` are honored once the register fix lands. Until then the new tenant takes the default name and the free plan regardless of what you pass.

### Way B. Insert a platform tenant directly into the database

Useful for scripted bulk onboarding.

```sql
INSERT INTO tenants (id, name, plan)
VALUES (gen_random_uuid(), 'New Customer Corp', 'pro')
RETURNING id;
```

Then attach the first admin user to it.

```sql
INSERT INTO users (id, tenant_id, email, password_hash, role, is_active)
VALUES (gen_random_uuid(), '<the-uuid>', 'admin@newcustomer.com', '<bcrypt>', 'admin', true);
```

### Way C. Mint a standalone API key in a new platform tenant

This is the path you want if you have a customer who should run their own copy of a standalone application but bill against their own platform tenant.

1. Create a platform tenant using way A or way B.
2. Mint a standalone key against that tenant.

```bash
curl -X POST $ABENIX_URL/api/api-keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"name":"standalone-contractiq-newcustomer","tenant_id":"<the-uuid>","scopes":{"allowed_actions":["can_delegate","execute","list","read"]}}'
```

`scopes` is honored once the api_keys fix lands. The endpoint already accepts the field but earlier versions stored a default `{}` regardless of input. Verify with `GET /api/api-keys/<id>` after creation.

3. Set `CONTRACTIQ_ABENIX_API_KEY` to the new key value in the new customer's ContractIQ deployment secrets.

After this, the new ContractIQ deployment routes all its agent traffic through the new platform tenant. It has its own quotas, its own executions list, its own billing envelope.

### Way D. Create an end user tenant inside a standalone application

Each standalone application has its own user table and its own registration endpoint. For ContractIQ.

```bash
curl -X POST $CIQ_URL/api/contractiq/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"trader@engie.com","password":"<strong>","tenant_name":"Engie Commodities"}'
```

ContractIQ creates a new row in `contractiq_users` with a fresh local `tenant_id`. Every subsequent ContractIQ query filters by it. The platform side is untouched.

## Picking the right layer for your goal

If your goal is to onboard a new platform customer who needs their own quota and billing envelope, create a platform tenant and mint their own standalone key in it. Use ways A or B for the tenant, then way C for the key.

If your goal is to let an analyst at an existing customer have their own contracts collection, create a new local tenant inside the standalone application. Use way D.

If your goal is to spin up a separate ContractIQ deployment for a specific customer, create their platform tenant, mint a `standalone-contractiq-<their-name>` key against it, then point their ContractIQ pod at that key. Combine ways A or B, then C, then D.

If your goal is just to give someone a login on an existing standalone application, create a user inside that application's user table. Use way D.

## Cleanup

To drop a test tenant and every user that belongs to it, run this against the database pod. Replace the email or uuid in the WHERE clause to target your test row.

```sql
DELETE FROM api_keys WHERE tenant_id = (SELECT id FROM tenants WHERE name = 'New Customer Corp');
DELETE FROM users    WHERE tenant_id = (SELECT id FROM tenants WHERE name = 'New Customer Corp');
DELETE FROM tenants  WHERE name = 'New Customer Corp';
```

If foreign keys complain, run the same DELETE against `executions`, `agents`, `code_assets`, and `knowledge_collections` first, all keyed on the same tenant_id. The platform never hard deletes in normal flows, so this path is for test cleanup only.

## The takeaway

Today everything in the cluster runs under one platform tenant called Abenix. Below that, each standalone application carries its own user table with its own local tenant scopes. The two layers do not talk to each other directly. The platform side sees one big bucket of traffic. The standalone side sees its own customers neatly separated.

Whether this is the right shape for your real customers depends on whether they need to be billed and quota'd separately at the platform level. If yes, give each customer their own platform tenant and their own standalone key. If no, leave them inside the shared Abenix tenant and rely on the standalone application's own tenant column to keep their data apart.
