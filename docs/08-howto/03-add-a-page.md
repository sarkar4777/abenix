# How to add a new UI page

> The Next.js App Router makes adding a route easy. The work is in fitting the established patterns: sidebar entry and gate, permission check on the page, loading and empty states, and visible feedback on every write.

---

## The 5-minute scaffold

```bash
mkdir -p apps/web/src/app/\(app\)/widgets
```

Create `apps/web/src/app/(app)/widgets/page.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { Sparkles } from 'lucide-react';
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

  if (perms && !canView) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center">
        <h1 className="text-xl font-semibold text-white">Widgets</h1>
        <p className="text-slate-400 mt-2">Viewing widgets needs the widgets.view capability. An admin can grant it under Admin, Permissions.</p>
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
    <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
      <header className="flex items-center gap-3">
        <Sparkles className="w-5 h-5 text-cyan-400" />
        <div>
          <h1 className="text-xl font-bold text-white">Widgets</h1>
          <p className="text-sm text-slate-400">All your widgets in one place.</p>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-6">
        <aside className="col-span-4 space-y-2">
          {isLoading && !widgets && [0, 1, 2].map(i => <div key={i} className="h-14 rounded-lg bg-slate-800/40 animate-pulse" />)}
          {(widgets || []).map(w => (
            <button key={w.id} onClick={() => setSelected(w)}
              className={`w-full p-3 rounded-lg border text-left ${
                selected?.id === w.id
                  ? 'bg-cyan-500/10 border-cyan-500/30 text-white'
                  : 'border-slate-700 text-slate-300 hover:bg-slate-800/50'
              }`}>
              <div className="font-medium">{w.name}</div>
              <div className="text-xs text-slate-400">{w.status}</div>
            </button>
          ))}
          {!isLoading && (widgets || []).length === 0 && (
            <p className="text-xs text-slate-400 text-center py-6">No widgets yet</p>
          )}
        </aside>

        <section className="col-span-8">
          {selected ? (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
              <h2 className="text-lg font-bold text-white">{selected.name}</h2>
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
2. **Use `useApi` for reads.** Pass `null` as the key to skip a fetch you aren't allowed to make.
3. **Use `apiFetch` for writes.** It handles auth, refresh and the error envelope. See [05-ui/02-api-client](../05-ui/02-api-client.md).
4. **Show feedback on every write.** A toast, an inline notice or a field error. Never silent.
5. **Render a skeleton while loading**, not blank space.
6. **Render an empty state with a next step**, never just "0 results".
7. **Check capabilities on the page** when it has one, and swap the controls for a "needs X" note.
8. **Use the design tokens.** slate-900/800 backgrounds, slate-300/400 text, cyan-500 for primary actions.
9. **Add a sidebar entry** if people should find it there (below).

---

## Adding the sidebar entry

`apps/web/src/components/layout/Sidebar.tsx` has one `NAV_GROUPS` array. The group ids are `pinned`, `build`, `run`, `monitor`, `monetize`, `admin` and `workspace`. Add your item to the right group:

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

Admin-default features (`review_queue`, `manage_settings`, `manage_team`) and capability items stay hidden until the permissions call lands, so nothing flashes. A group with nothing visible disappears. The label you give the item also becomes the top bar breadcrumb for that route, through `NAV_ROUTE_LABELS`.

`external: true` opens the link in a new tab. `badge` adds a small pill.

If the page lives under `/settings/*`, add it to `NAV_ITEMS` in `apps/web/src/app/(app)/settings/layout.tsx` too. That nav is not gated.

The full rules are in [05-ui/00-app-shell](../05-ui/00-app-shell.md#sidebar-and-gating).

---

## Backing the gate on the server

The sidebar and page checks are UX. The API has to enforce the same thing.

**A new capability.** Add it to `CATALOG` in `apps/api/app/core/capabilities.py` with a label, group and description. That makes it appear on `/admin/permissions` so admins can put it in a permission set. Add it to `ROLE_DEFAULTS` for any role that should have it out of the box. `admin` already holds `*`. Then guard the route:

```python
from app.core.capabilities import require_capability

@router.get("")
async def list_widgets(
    user: User = Depends(require_capability("widgets.view")),
    db: AsyncSession = Depends(get_db),
):
    ...
```

A caller without it gets a 403 that names the capability. Inside a handler, `await has_capability(db, user, "widgets.manage")` gives you a bool.

**A new feature flag.** Add it to every row of `ROLE_FEATURES` in `apps/api/app/core/permissions.py` that should differ from the `user` row. Guard the route with `require_role([...])` from `app.core.deps` or your own check, since the flag alone protects nothing.

---

## Backend endpoint

The frontend assumes `/api/widgets` exists. Add it to abenix-api:

```python
# apps/api/app/routers/widgets.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_db
from app.core.responses import success
from models.user import User
from models.widget import Widget  # model defined and created at startup

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

Errors go through `error(message, code, error_code=..., details=...)` from `app.core.responses` so the page can branch on `error_code`.

---

## Tests

### Backend (pytest)

`apps/api/tests/conftest.py` gives you a `client` fixture. Existing tests register a user and pass its token:

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

### E2E (Playwright)

Add to `e2e/uat_audit_fixes.spec.ts` (it already has `login(page)` and `BASE`) or create a focused spec:

```ts
test('Widgets page renders + empty state', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/widgets`);
  await expect(page.locator('h1', { hasText: 'Widgets' })).toBeVisible();
  await expect(page.locator('text=No widgets yet')).toBeVisible();
});
```

Run: `npx playwright test e2e/your-spec.ts`.

---

## Building docs for it

If the page is user-facing, add it to `/help` and capture a screenshot:

1. Add a section to `apps/web/src/app/(app)/help/page.tsx` (copy a sibling section as template).
2. Add a test to `e2e/capture_audit_screenshots.spec.ts` that opens your page and saves a PNG to `apps/web/public/docs-screenshots/`.

For developers, add the route to [05-ui/03-page-catalogue](../05-ui/03-page-catalogue.md) with its sidebar label, gate and purpose.

---

## Common mistakes

| Mistake | Fix |
|---|---|
| Forgetting `'use client'` on a page with hooks | Add it at the top of the file |
| Using `useApi` for writes | Use `apiFetch`. `useApi` is for cached reads |
| `console.error` on failure | Show it with `toastError` or an inline notice |
| A capability in the sidebar but not on the route | Add `require_capability` to the handler |
| A new capability that never shows on `/admin/permissions` | Add it to `CATALOG` |
| Gating with `permission:` | There is no such field. Use `capability`, `feature` or `adminOnly` |
| Rendering `<main>` in the page | The shell already has one. Use `<section>` |
| No empty state | Always render one when the list is empty |
| Forgetting the sidebar entry | Add it to `NAV_GROUPS`, or link to the page from somewhere |
| No mobile fallback | Test under 768px in DevTools and degrade to a simpler form |

---

## See also

- [05-ui/00-app-shell](../05-ui/00-app-shell.md) — layout, auth, sidebar gating
- [05-ui/02-api-client](../05-ui/02-api-client.md) — apiFetch, useApi, error envelope
- [05-ui/03-page-catalogue](../05-ui/03-page-catalogue.md) — every route with its gate
