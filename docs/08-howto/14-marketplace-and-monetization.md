# Marketplace and monetization

Two switches, each independent of the other.

| Switch | What it turns on | Default |
|---|---|---|
| `marketplace` | The store, free listing with admin review, installing a listed agent, ratings, Creator Hub | on |
| `monetization` | Paid listings, Stripe checkout and Connect, creator revenue and payouts, the Billing tab in Settings, plan limits and upgrade prompts | off |

With the marketplace on and monetization off, every listing is free. That is the default.

## Who flips them

A platform operator, on **Admin > Marketplace & Billing** (`/admin/marketplace`). The page calls `PUT /api/admin/platform-features` with `marketplace`, `monetization` or both, and the change is written to the audit log as `platform.features_changed`.

The switches are stored in `platform_settings`, which is shared by the whole deployment. Flipping one changes it for every tenant, so a tenant admin cannot do it. Anyone can register a tenant and become its admin, which is why the old admin-role check was not enough.

A platform operator is a user with the admin role who is either:

- listed in `ABENIX_PLATFORM_OPERATORS`, a comma separated list of emails. When it is set, only the listed admins are operators.
- an admin of the platform tenant, the one that holds `system@abenix.dev`, when `ABENIX_PLATFORM_OPERATORS` is unset. On a fresh install that includes `admin@abenix.dev`.

Other admins still open the page. They see the current values, the toggles are locked, and a note explains that only a platform operator can change them and who that is. `GET /api/admin/platform-features` returns the switches plus `can_change` and `operator_rule` for the caller. A refused `PUT` answers 403 with `error_code = PLATFORM_OPERATOR_REQUIRED`.

The switches stay deployment-wide rather than per tenant. The marketplace lists agents across tenants and monetization runs one Stripe account, so a per-tenant value would not mean anything coherent.

## Where the value comes from

1. An operator value, stored under `features.marketplace.enabled` and `features.monetization.enabled`.
2. Without an admin value, the env default: `MARKETPLACE_ENABLED` (default `true`) and `MONETIZATION_ENABLED` (default `false`). The chart sets them from `features.marketplace` and `features.monetization` in the values file.

`GET /api/platform/features` returns both values, where each came from (`admin` or `default`) and the env defaults. It needs no sign-in. The web reads it at run time, so no rebuild is needed when an operator flips one. `NEXT_PUBLIC_ENABLE_MONETIZATION` is no longer read.

## What each switch hides when off

Marketplace off:

- `/api/marketplace/*`, `/api/creator/listings` and `/api/agents/{id}/reviews` answer 404 `MARKETPLACE_OFF`.
- Publishing with `visibility: public` and approving a pending submission answer 409 `MARKETPLACE_OFF`.
- The sidebar drops **Marketplace** and **Creator Hub**. Both entries carry `requires: 'marketplace'` in [`Sidebar.tsx`](../../apps/web/src/components/layout/Sidebar.tsx). The command palette, top bar search, the My Agents tab and the builder's publish dialog drop their marketplace entries too.
- Agents someone already installed keep working.

Monetization off:

- `/api/billing/plans`, `checkout`, `portal`, `webhook` and `/api/creator/onboard`, `status`, `dashboard`, `login-link` answer 404 `MONETIZATION_OFF`.
- Publishing with a price is refused with 409. Publishing an agent that had a price clears the price, so it is listed free.
- Existing paid listings leave the store. Installing one answers 409.
- The **Billing** tab in Settings (`/settings/billing`) is hidden. Opening the URL directly shows a note that monetization is off.
- The plan's daily run cap and its upgrade warning do not apply. Token quotas on Settings > Token Quotas still do.
- `/api/billing/usage` stays open for analytics.

## Listing flow

1. A creator opens **Creator Hub**, picks one of their agents and submits it. The builder's Publish dialog with Marketplace visibility does the same. Both call `POST /api/agents/{id}/publish` with `visibility: public`.
2. The agent moves to `pending_review` and shows on the **Marketplace submissions** tab of the review inbox (`/review-queue`, sidebar **Review inbox**).
3. An admin approves or rejects it with `POST /api/agents/{id}/review`. The creator gets a `listing_reviewed` notification.
4. The agent shows in the store. Anyone signed in can open it and install it, then run it from My Agents or chat.
5. Creator Hub shows each listing with its state, installs, runs in the last 30 days and ratings. Revenue and payouts only appear while monetization is on.

Only the agent's creator or an admin can publish, and only roles with the `publish_to_marketplace` feature (creator and admin by default) can list publicly. A user-role account sees why on Creator Hub and asks an admin to change their role in Settings > Team.

## Claude subscription

When the Claude subscription is active, `/api/billing/usage` returns `billing_mode: claude_subscription` and the cost fields read 0. The Billing page labels the $0 as Claude subscription.

## Where to look

- Switches: [`apps/api/app/core/platform_features.py`](../../apps/api/app/core/platform_features.py), [`apps/api/app/routers/platform_features.py`](../../apps/api/app/routers/platform_features.py)
- Web hook: [`apps/web/src/hooks/usePlatformFeatures.ts`](../../apps/web/src/hooks/usePlatformFeatures.ts)
- Store, billing, creator: [`marketplace.py`](../../apps/api/app/routers/marketplace.py), [`billing.py`](../../apps/api/app/routers/billing.py), [`creator.py`](../../apps/api/app/routers/creator.py)

## Tests

- Unit: `tests/unit/test_platform_features.py`
- Browser: `e2e/uat_marketplace_ui.spec.ts`
