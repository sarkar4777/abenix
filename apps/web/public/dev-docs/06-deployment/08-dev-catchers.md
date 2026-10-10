# Dev catchers: email, Slack and SSO on a local cluster

A local cluster has no mail server, no Slack workspace and no identity provider. Three small dev-only services stand in for them, so password resets, invites, notification delivery and single sign-on can be tested end to end from the browser.

| Service | Image | In the cluster | On your machine |
|---|---|---|---|
| Mailpit | `axllent/mailpit:v1.21` | SMTP on `abenix-mailpit:1025` | inbox at http://localhost:8025 |
| Webhook catcher | `python:3.12-alpine` running `infra/helm/abenix/files/webhook-catcher.py` | `http://abenix-webhook-catcher:8080/<any path>` | http://localhost:8091 |
| Mock OIDC | `ghcr.io/navikt/mock-oauth2-server:2.1.10` | `abenix-mock-oidc:8080` | issuer http://localhost:8090/default |

They live in `templates/dev-catchers.yaml` and render only when `devCatchers.enabled` is true. The chart default is false. `values-local.yaml` turns them on and `scripts/deploy.sh local` passes `devCatchers.enabled=${DEV_CATCHERS}`, which defaults to true. Run `DEV_CATCHERS=false bash scripts/deploy.sh local` to leave them out.

Never turn them on in a shared or production cluster. Mailpit accepts any login and the catcher keeps every request it gets in memory.

## What changes when they are on

The `abenix-config` ConfigMap picks up:

- `SMTP_HOST=abenix-mailpit`, `SMTP_PORT=1025`, `SMTP_STARTTLS=false`. Every email the API sends lands in Mailpit.
- `EVENTS_ALLOWED_INTERNAL_HOSTS` gains `abenix-webhook-catcher` and its full service name. That is the only reason a Slack webhook or an event subscription may point at the catcher, and plain `http://` is accepted only for a host on that list.
- `OIDC_INTERNAL_URL_MAP=http://localhost:8090=http://abenix-mock-oidc.abenix.svc.cluster.local:8080`. The browser reaches the mock on the forwarded localhost port while the API reaches the same server by service name. The API maps the provider's URLs both ways.
- `DEV_CATCHERS=true`, so the pods can tell.

`deploy.sh local` also sets `frontendUrl` and `publicApiUrl` from `WEB_PORT` and `API_PORT`, so links in emails and Slack posts and the SSO redirect address point at the ports you actually use.

With the catchers off the guards are the production ones. A Slack webhook or an SSO issuer must be `https://` and must resolve to a public address. Loopback, private ranges, link local and cluster DNS names are refused when you save and again when the API sends.

## Forwards

`bash scripts/deploy.sh forwards` starts and checks them with the rest. The ports move with `MAILPIT_PORT`, `CATCHER_PORT` and `MOCK_OIDC_PORT`. If you move `MOCK_OIDC_PORT`, set `devCatchers.mockOidc.publicUrl` to match, the issuer the browser sees has to be the one the map names.

## Reading things back

Mailpit has a full API at http://localhost:8025/api/v1. The handy calls:

```bash
curl -s 'http://localhost:8025/api/v1/search?query=to:someone@example.com'   # newest first
curl -s http://localhost:8025/api/v1/message/<ID>                             # Text, HTML, headers
curl -s -X DELETE http://localhost:8025/api/v1/messages                       # empty the inbox
```

The catcher stores the last 500 requests:

```bash
curl -s 'http://localhost:8091/api/requests?path=/hooks/my-run'   # JSON, newest first
curl -s -X DELETE http://localhost:8091/api/requests              # clear
```

Open http://localhost:8091 for a plain table of what arrived. To send notifications there, paste `http://abenix-webhook-catcher:8080/hooks/<anything>` into Settings, Notifications, Workspace Slack channel. Use a path per test run so runs do not read each other's posts.

## Single sign-on against the mock

1. Sign in as a workspace admin and open Settings, Single sign-on.
2. Issuer `http://localhost:8090/default`, any client ID and secret, an email domain such as `sso-test.dev`, and the role new people get.
3. Test connection, then Save.
4. Sign out. On the sign-in page choose Sign in with your company (SSO) and type an address in that domain.
5. The mock shows a login form. Type any user name and, in the claims box, at least the email, for example `{"email": "pat@sso-test.dev", "name": "Pat"}`. The mock does not add an email on its own.
6. You land in the workspace with the role you picked. A second sign-in with the same user name finds the same account.

## Tests that use them

- `e2e/uat_account_security_ui.spec.ts` covers sign up, forgot password through Mailpit, change password, sign out, the device list, two-step sign-in and SSO through the mock.
- `e2e/uat_notifications_delivery_ui.spec.ts` sets the catcher as the Slack channel, turns on email and checks that a failed run, an approval request and a harm flag arrive with working links, and that a turned off preference stops them.

Both expect `BASE=http://localhost:3100 API=http://localhost:8000` and the default catcher ports.
