# How to add a new UI page

> The Next.js App Router makes adding a route easy. The work is in fitting the established patterns: a `PageHeader`, a sidebar entry and gate, a permission check on the page, loading and empty states, visible feedback on every write, and passing the lostness gate.

---

## The 5-minute scaffold

```bash
mkdir -p "apps/web/src/app/(app)/widgets"
```

Create `apps/web/src/app/(app)/widgets/page.tsx`:

```tsx
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Plus, Sparkles } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { toastSuccess, toastError } from '@/stores/toastStore';

interface Widget {
  id: string;
  name: string;
  status: string;
}

export default function WidgetsPage() {
  const { perms } = useMyPermissions();
  const canView = holds(perms?.capabilities, 'widgets.view');
  const canManage = holds(perms?.capabilities, 'widgets.manage');
  const { data: widgets, isLoading, mutate } = useApi<Widget[]>(canView ? '/api/widgets' : null);
  const [selected, setSelected] = useState<Widget | null>(null);

  const header = (
    <PageHeader
      title="Widgets"
      icon={Sparkles}
      storageKey="widgets"
      purpose="Keep track of every widget your agents use. For builders."
      primaryAction={
        canManage
          ? { label: 'New widget', href: '/widgets/new', icon: Plus }
          : { label: 'New widget', icon: Plus, disabled: true, title: 'Needs the widgets.manage capability' }
      }
      steps={['Create a widget', 'Pick it on the left to see its detail', 'Archive it when you no longer need it']}
      docSlug="08-howto/03-add-a-page"
    />
  );

  if (perms && !canView) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8 space-y-6">
        {header}
        <p className="text-slate-400">
          You do not have access to widgets. Viewing them needs the widgets.view capability, which an
          admin can grant under Admin, Permissions. <Link href="/dashboard" className="text-cyan-300 hover:underline">Back to Home</Link>
        </p>
      </div>
    );
  }

  async function archive(w: Widget) {
    const r = await apiFetch(`/api/widgets/${w.id}/archive`, { method: 'POST', throwOnError: false });
    if (r.error) return toastError('Could not archive', r.error);
    toastSuccess('Archived', w.name);
    mutate();
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-6">
      {header}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <section className="space-y-2 lg:col-span-4">
          {isLoading && !widgets && [0, 1, 2].map(i => <div key={i} className="h-14 rounded-lg bg-slate-800/40 animate-pulse" />)}
          {(widgets || []).map(w => (
            <button key={w.id} onClick={() => setSelected(w)}
              className={`w-full p-3 rounded-lg border text-left ${
                selected?.id === w.id
                  ? 'bg-cyan-500/10 border-cyan-500/30 text-white'
                  : 'border-slate-700 text-slate-300 hover:bg-slate-800/50'
              }`}>
              <div className="font-medium break-words">{w.name}</div>
              <div className="text-xs text-slate-400">{w.status}</div>
            </button>
          ))}
          {!isLoading && (widgets || []).length === 0 && (
            <p className="text-xs text-slate-400 text-center py-6">No widgets yet. Create one with New widget.</p>
          )}
        </section>

        <section className="lg:col-span-8">
          {selected ? (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
              <h2 className="text-lg font-bold text-white break-words">{selected.name}</h2>
              {canManage && (
                <button onClick={() => archive(selected)} className="mt-3 text-sm text-cyan-300 hover:underline">Archive</button>
              )}
            </div>
          ) : (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-12 text-center">
              <p className="text-sm text-slate-400">Pick a widget on the left.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
```

Visit `/widgets` and the page renders inside the shell. Next.js discovers the route from the folder.

Use `<section>` or `<div>` for the page body, not `<main>`. The shell already renders the `<main>` landmark.

---

## Conforming to the design patterns

Every page in `(app)/` should:

1. **Sit under `(app)/`** so it gets `AuthGuard`, the sidebar and the top bar from `(app)/layout.tsx`.
2. **Start with `PageHeader`**, also when the person cannot use the page (below).
3. **Use `useApi` for reads.** Pass `null` as the key to skip a fetch you aren't allowed to make.
4. **Use `apiFetch` for writes.** It handles auth, refresh and the error envelope. See [05-ui/02-api-client](../05-ui/02-api-client.md).
5. **Show feedback on every write.** A toast, an inline notice or a field error. Never silent.
6. **Show `NextSteps` after a success** that starts something new (below).
7. **Render a skeleton while loading**, not blank space.
8. **Render an empty state with a next step**, never a bare "0 results".
9. **Check capabilities on the page** when it has one, and swap the controls for a plain "needs X" note with a link onward.
10. **Work at 390 px.** One column on phones, no fixed widths that push the page sideways.
11. **Use the design tokens.** slate-900/800 backgrounds, slate-300/400 text, cyan-500 for primary actions.
12. **Add a sidebar entry** if people should find it there, and decide whether it belongs in Essentials (below).

---

## PageHeader

[`apps/web/src/components/layout/PageHeader.tsx`](../../apps/web/src/components/layout/PageHeader.tsx) is the same top block on every page. The props that matter:

| Prop | What it renders |
|---|---|
| `title` | The `<h1>` |
| `purpose` | One plain sentence on what the page is for and who it is for. `data-testid="page-purpose"` |
| `primaryAction` | `{label, href or onClick, icon, disabled, title, testId}`, or any React node. Wrapped in `data-testid="page-primary-action"`. Full width on phones |
| `secondaryAction`, `extraActions` | A second button, and small things such as a refresh button |
| `steps` | Two to four "How this works" steps, plain strings or `{title, body}` |
| `howItWorks` | Extra text under the steps |
| `docSlug` | A Docs link to `/docs?doc=<slug>`. The slug is a path under `docs/` without `.md`, listed in `docs/manifest.json` |
| `storageKey` | Remembers whether How this works is open, under `pageHeader.how.<key>` in `localStorage`. Open on the first visit, collapsed after that |
| `back`, `meta`, `icon` | A back link, badges next to the title, and the title icon |
| `compact` | One short row for full-height tool pages. How this works starts shut |

The whole block carries `data-testid="page-header"`. Pass existing test ids through `titleTestId`, `howTestId`, `howToggleTestId` and the action's `testId`.

A disabled primary action still counts as visible. Give it a `title` that says why it is disabled.

More on the header, the dashboard's Start here guide and next steps is in [05-ui/00-app-shell](../05-ui/00-app-shell.md#page-header-start-here-and-next-steps).

---

## NextSteps after a success

When a write creates something a person will want to use next, show [`NextSteps`](../../apps/web/src/components/shared/NextSteps.tsx) right after it:

```tsx
import { FlaskConical, Workflow } from 'lucide-react';
import NextSteps from '@/components/shared/NextSteps';

{justCreated && (
  <NextSteps
    title={`${justCreated.name} is in. What next?`}
    testId="widget-next-steps"
    onDismiss={() => setJustCreated(null)}
    steps={[
      { id: 'agent', label: 'Use in an agent', hint: 'Open the builder with the widget tool added.', icon: Workflow, href: '/builder?tool=widget_lookup' },
      { id: 'test', label: 'Try it', hint: 'Run it once against an example.', icon: FlaskConical, onClick: runTest },
    ]}
  />
)}
```

Each step has an `id`, a `label`, a one-line `hint`, an `icon`, and either `href` or `onClick`. Only the first four show. Each card gets `data-testid="<testId>-<id>"`, which is what the first-use test follows (below). The default title is "Done. What next?".

---

## Adding the sidebar entry

`apps/web/src/components/layout/Sidebar.tsx` has one `NAV_GROUPS` array, the full list a person sees under **Show all tools**. The group ids are `pinned`, `build`, `run`, `monitor`, `monetize`, `admin` and `workspace`. Add your item to the right group:

```ts
{
  id: 'build',
  label: 'BUILD',
  defaultOpen: true,
  items: [
    { label: 'Agent Builder', icon: Wand2,    href: '/builder',   feature: 'use_builder' },
    { label: 'Decisions',     icon: Scale,    href: '/decisions', capability: 'decisions.view' },
    { label: 'Widgets',       icon: Sparkles, href: '/widgets',   capability: 'widgets.view' },  // <- new
  ],
},
```

Pick one gate:

| Field | Shown when | Use it for |
|---|---|---|
| `capability: 'x.y'` | `/api/me/permissions` `capabilities` holds it | anything a tenant should be able to grant to some people and not others |
| `feature: 'x'` | `features.x` is not `false` | coarse role switches from `ROLE_FEATURES` |
| `adminOnly: true` | the user is an admin | platform operations |
| none | always | pages everyone should see |

Other fields: `orCapability` shows a `feature` item to someone who holds that capability, `requires: 'marketplace'` or `'monetization'` hides the item while that platform switch is off, `liveCount` adds a live count badge, `badge` adds a small pill and `external: true` opens the link in a new tab.

Admin-default features (`review_queue`, `manage_settings`, `manage_team`) and capability items stay hidden until the permissions call lands, so nothing flashes. A group with nothing visible disappears. The label you give the item also becomes the top bar breadcrumb for that route, through `NAV_ROUTE_LABELS`.

If the page lives under `/settings/*`, add it to `NAV_ITEMS` in `apps/web/src/app/(app)/settings/layout.tsx` too. That nav is not gated.

### Essentials or not

The sidebar opens in **Essentials** mode, a short list in the `ESSENTIALS` array in the same file. Today it holds Needs you, the review inbox (for reviewers), Home, Agents, AI Chat, Knowledge and Monitor for everyone, plus Agent Builder, Autonomy and Improvements for admins and creators (`builders: true`). Admins also get the admin group folded under one Admin entry.

Most new pages do not belong there. Add an entry only when most people of a role need the page every week. An entry names an `href` that must already be in `NAV_GROUPS`, and can override `label` and `icon`, set `builders: true` or require a `capability`. A page left out is still reachable from **Show all tools**, the command palette and links from other pages, and while it is open the sidebar shows it under "You are here".

The full rules are in [05-ui/00-app-shell](../05-ui/00-app-shell.md#sidebar-and-gating).

---

## Passing the lostness gate

`e2e/uat_lostness_gate.spec.ts` reads every `href` in `NAV_GROUPS` (external links skipped) the moment it runs, so a new sidebar entry is tested the day it lands. It opens each route as four people, an admin, a creator, a member and a member with no extra permission sets, at 390 px and 1440 px. It visits every route for every role, whether or not the sidebar would show it to them.

For each visit the page must either explain that it is not for this role or pass all of these:

- it stays on the route. A redirect counts only when the page explains it
- `page-header` is visible, with a `page-purpose` of at least 10 characters
- the purpose line is at least 160 px wide on a phone and 240 px on desktop, and at most four lines
- `page-primary-action` is visible and inside the viewport, or the page says plainly that there is nothing to do yet or why the person cannot act, for example "No widgets yet" or "You do not have access"
- the header does not overlap the content after it
- no Python traceback, JavaScript stack trace, crash screen, raw JSON, `[object Object]`, raw HTTP error such as "Server error (500)", `NaN` or `undefined` in the visible text
- no raw error code such as `WIDGET_NOT_FOUND` outside `code`, `kbd` or `pre`
- no sideways scroll at either width
- no script error on the page

"Not for this role" means text such as "You do not have access", "needs the widgets.view capability", "only admins" or "ask your admin", plus at least one link inside `<main>`. The scaffold above does this and still shows the header. A blank page or a bare `return null` fails.

Run it against a running stack with the seeded admin. It invites the three other people from **Settings, Team** and removes them at the end:

```bash
USE_K8S=true BASE=http://localhost:3000 API=http://localhost:8000 \
  npx playwright test e2e/uat_lostness_gate.spec.ts --workers=1
```

`BASE` defaults to `http://localhost:3100` in this spec, so pass it when your web app is on 3000. `AF_EMAIL` and `AF_PASSWORD` override the admin login. It writes `e2e/uat_lostness_gate/report.md` and `report.json`, and fails with every problem in one table. More in [05-testing](05-testing.md).

## The first-use tasks

`e2e/uat_first_use_tasks.spec.ts` times three new-person journeys through the UI, following only what the screen tells them:

| Task | Limit | Path |
|---|---|---|
| A new creator builds an agent with a knowledge base and gets a correct answer | 10 minutes | Start here on the dashboard, the Knowledge Bases primary action, the knowledge base next steps, Use in agent, the builder, Publish, then chat |
| A new member finds an agent, follows up in the same chat and leaves feedback with the thumbs | 3 minutes | Start here, chat, the agent picker, the chat history, the feedback bar |
| An admin clears a waiting approval from Needs you | 2 minutes | The Needs you count in the sidebar, the Approvals tab, approve inline |

Each step looks for its guidance by test id: the `start-here-<step>-go` buttons, `page-primary-action`, `NextSteps` cards such as `kb-next-steps`, and the `sidebar-inbox-count`. When the guidance is missing the task fails with the step where a person would be lost.

Run it the same way as the gate, with `e2e/uat_first_use_tasks.spec.ts`. It needs a working LLM credential, since the creator's agent has to answer from the uploaded document. Step times go to `e2e/uat_first_use_tasks/report.json`.

A new page only touches this test if it sits on one of those paths. If you change a page on the path, keep its test ids and its next steps. If your page adds something a new person must do first, add a step to Start here (`apps/api/app/routers/journey.py` and [`StartHere.tsx`](../../apps/web/src/components/shared/StartHere.tsx)) rather than relying on people finding the sidebar entry.

---

## Backing the gate on the server

The sidebar and page checks are UX. The API has to enforce the same thing.

**A new capability.** Add it to `CATALOG` in `apps/api/app/core/capabilities.py` as `Capability(key, label, group, description)`. That makes it appear on `/admin/permissions` so admins can put it in a permission set. Add it to `ROLE_DEFAULTS` for any role that should have it out of the box (`user` and `creator` are listed, `admin` already holds `*`). Then guard the route:

```python
from app.core.capabilities import require_capability

@router.get("")
async def list_widgets(
    user: User = Depends(require_capability("widgets.view")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

A caller without it gets a 403 that names the capability. Inside a handler, `await has_capability(db, user, "widgets.manage")` gives you a bool. The web side checks the same rules with `holds()` from `@/lib/capabilities`, including `group.*` grants.

**A new feature flag.** Add it to every row of `ROLE_FEATURES` in `apps/api/app/core/permissions.py` that should differ from the `user` row. Guard the route with `require_role([...])` from `app.core.deps` or your own check, since the flag alone protects nothing.

---

## Backend endpoint

The frontend assumes `/api/widgets` exists. Add it to the API:

```python
# apps/api/app/routers/widgets.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_db
from app.core.responses import success
from models.user import User
from models.widget import Widget  # your model, with an Alembic migration

router = APIRouter(prefix="/api/widgets", tags=["widgets"])


@router.get("")
async def list_widgets(
    user: User = Depends(require_capability("widgets.view")),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Widget).where(Widget.tenant_id == user.tenant_id))
    return success([{"id": str(w.id), "name": w.name, "status": w.status} for w in q.scalars()])
```

Wire it in [`apps/api/app/main.py`](../../apps/api/app/main.py):

```python
from app.routers import widgets
app.include_router(widgets.router)
```

Errors go through `error(message, code, error_code=..., details=...)` from `app.core.responses` so the page can branch on `error_code`. Show the person a sentence, not the code.

---

## Tests

### Backend (pytest)

`apps/api/tests/conftest.py` gives you a `client` fixture backed by the database in the API's settings, so run these with `bash scripts/dev-local.sh` up. Existing tests register a user and pass its token:

```python
import uuid
import pytest
from httpx import AsyncClient


async def _token(client: AsyncClient) -> str:
    r = await client.post("/api/auth/register", json={
        "email": f"w-{uuid.uuid4().hex[:8]}@test.com",
        "password": "securepass123",
        "full_name": "Widget Tester",
    })
    return r.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_list_widgets(client: AsyncClient):
    token = await _token(client)
    r = await client.get("/api/widgets", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["data"] == []
```

Logic that needs no database is better as a unit test under `tests/unit/`, which CI runs on every push.

### E2E (Playwright)

Add to `e2e/uat_audit_fixes.spec.ts` (it already has `login(page)` and `BASE`) or create a focused spec:

```ts
test('Widgets page renders + empty state', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/widgets`);
  await expect(page.getByTestId('page-header')).toBeVisible();
  await expect(page.locator('text=No widgets yet')).toBeVisible();
});
```

Run it against a running stack: `USE_K8S=true npx playwright test e2e/your-spec.ts`. Then run the lostness gate, see [05-testing](05-testing.md).

---

## Building docs for it

If the page is user-facing, add it to `/help` and capture a screenshot:

1. Add a section to `apps/web/src/app/(app)/help/page.tsx` (copy a sibling section as template).
2. Add a test to `e2e/capture_audit_screenshots.spec.ts` that opens your page and saves a PNG to `apps/web/public/docs-screenshots/`.

For developers, add the route to [05-ui/03-page-catalogue](../05-ui/03-page-catalogue.md) with its sidebar label, gate and purpose. If you point `docSlug` at a new doc, add it to `docs/manifest.json`.

---

## Common mistakes

| Mistake | Fix |
|---|---|
| Forgetting `'use client'` on a page with hooks | Add it at the top of the file |
| No `PageHeader`, or one only on the happy path | Render it in every branch, including the no-access note |
| A no-access note with no link | Add a link onward inside the page, the lostness gate needs one |
| Using `useApi` for writes | Use `apiFetch`. `useApi` is for cached reads |
| `console.error` on failure | Show it with `toastError` or an inline notice |
| Showing `error_code` or raw JSON to the person | Show a sentence. Codes go in `code` at most |
| A capability in the sidebar but not on the route | Add `require_capability` to the handler |
| A new capability that never shows on `/admin/permissions` | Add it to `CATALOG` |
| Gating with `permission:` | There is no such field. Use `capability`, `feature` or `adminOnly` |
| Rendering `<main>` in the page | The shell already has one. Use `<section>` |
| No empty state | Always render one when the list is empty |
| Forgetting the sidebar entry | Add it to `NAV_GROUPS`, or link to the page from somewhere |
| A fixed-width grid | Use one column below `lg` and check 390 px in DevTools |

---

## See also

- [05-ui/00-app-shell](../05-ui/00-app-shell.md), layout, auth, sidebar gating, Start here
- [05-ui/02-api-client](../05-ui/02-api-client.md), apiFetch, useApi, error envelope
- [05-ui/03-page-catalogue](../05-ui/03-page-catalogue.md), every route with its gate
- [05-testing](05-testing.md), running the lostness gate and the first-use tasks
