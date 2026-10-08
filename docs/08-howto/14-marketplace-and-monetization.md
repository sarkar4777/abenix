# Marketplace and monetization

Two switches, each independent of the other.

| Switch | What it turns on | Default |
|---|---|---|
| Marketplace | The store, free listing with admin review, installing a listed agent, ratings, Creator Hub | on |
| Monetization | Paid listings, Stripe checkout and Connect, creator revenue and payouts, the Billing page, plan limits and upgrade prompts | off |

With the marketplace on and monetization off, every listing is free. That is the default.

## Where the value comes from

1. An admin sets a switch on **Admin > Marketplace & Billing**. The value is stored in `platform_settings` under `features.marketplace.enabled` and `features.monetization.enabled`, so every API pod sees it.
2. Without an admin value the env default applies, `MARKETPLACE_ENABLED` and `MONETIZATION_ENABLED`. The chart sets them from `features.marketplace` and `features.monetization` in the values file.

The web reads both from `GET /api/platform/features` at runtime. No rebuild is needed when an admin flips one. `NEXT_PUBLIC_ENABLE_MONETIZATION` is no longer read.

## What each switch does when off

Marketplace off

- `/api/marketplace/*`, `/api/creator/listings` and `/api/agents/{id}/reviews` answer 404 `MARKETPLACE_OFF`.
- Publishing with `visibility: public` and approving a pending submission answer 409 `MARKETPLACE_OFF`.
- The sidebar, command palette, global search, the My Agents tab and the builder's publish dialog drop every marketplace entry.
- Agents someone already installed keep working.

Monetization off

- `/api/billing/plans`, `checkout`, `portal`, `webhook` and `/api/creator/onboard`, `status`, `dashboard`, `login-link` answer 404 `MONETIZATION_OFF`.
- A listing with a price is refused with 409. A listing that carried a price before is listed free.
- Paid listings leave the store. Installing one answers 409.
- The plan's daily run cap and its upgrade warning do not apply. Token quotas on Settings > Token Quotas still do.
- `/api/billing/usage` stays open for analytics.

## Listing flow

1. A creator opens **Creator Hub**, picks one of their agents and submits it. The builder's Publish dialog with Marketplace visibility does the same thing. Both call `POST /api/agents/{id}/publish` with `visibility: public`.
2. The agent moves to `pending_review` and shows in the admin review inbox.
3. An admin approves it with `POST /api/agents/{id}/review`. The creator gets a `listing_reviewed` notification.
4. The agent shows in the store. Anyone signed in can open it and install it, then run it from My Agents or chat.
5. Creator Hub shows each listing with its state, installs, runs in the last 30 days and ratings. Revenue and payouts only appear while monetization is on.

Only the creator and admin roles can list. A member sees why on Creator Hub and asks an admin to change their role in Settings > Team.

## Claude subscription

When the Claude subscription is active, `/api/billing/usage` returns `billing_mode: claude_subscription` and the cost fields read 0. The Billing page labels the $0 as Claude subscription.

## Tests

- Unit: `tests/unit/test_platform_features.py`
- Browser: `e2e/uat_marketplace_ui.spec.ts`
