# How to add a new UI page

> The Next.js App Router makes adding routes trivial — the work is in conforming to the established design patterns (sidebar entry, page skeleton, error envelope, toast feedback).

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
import { toastSuccess, toastError } from '@/stores/toastStore';

interface Widget {
  id: string;
  name: string;
  status: string;
}

export default function WidgetsPage() {
  const { data: widgets, mutate } = useApi<Widget[]>('/api/widgets');
  const [selected, setSelected] = useState<Widget | null>(null);

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="flex items-center gap-3">
          <Sparkles className="w-5 h-5 text-cyan-400" />
          <div>
            <h1 className="text-xl font-bold text-white">Widgets</h1>
            <p className="text-sm text-slate-400">All your widgets in one place.</p>
          </div>
        </header>

        <div className="grid grid-cols-12 gap-6">
          <aside className="col-span-4 space-y-2">
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
            {(widgets || []).length === 0 && (
              <p className="text-xs text-slate-400 text-center py-6">No widgets yet</p>
            )}
          </aside>

          <main className="col-span-8">
            {selected ? <WidgetDetail widget={selected} /> : <EmptyState />}
          </main>
        </div>
      </div>
    </div>
  );
}

function WidgetDetail({ widget }: { widget: Widget }) {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
      <h2 className="text-lg font-bold text-white">{widget.name}</h2>
      <p className="text-xs text-slate-400 mt-1">id={widget.id}</p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-12 text-center">
      <Sparkles className="w-10 h-10 text-cyan-400/30 mx-auto mb-3" />
      <p className="text-sm text-slate-400">Pick a widget on the left.</p>
    </div>
  );
}
```

That's it — visit `/widgets` and the page renders. Next.js auto-discovers the route.

---

## Conforming to the design patterns

Every page in `(app)/` should:

1. **Use the `(app)/layout.tsx` shell** — done automatically since you put the page there.
2. **Use `useApi` for GETs** — handles loading + revalidate.
3. **Use `apiFetch` for mutations** — handles auth + error envelope.
4. **Wrap mutations in try/catch + toast** — every success and every failure shows feedback.
5. **Render skeletons during load** — not blank space.
6. **Render empty states with a CTA** — never just "0 results."
7. **Use the design tokens** — slate-900/800 backgrounds, slate-300/400 text, cyan-500 for primary actions.
8. **Add a sidebar entry** (see below).

---

## Adding the sidebar entry

`apps/web/src/components/layout/Sidebar.tsx` has a sidebar groups array. Add your route to the relevant group:

```ts
const SIDEBAR_GROUPS = [
  // ...
  {
    label: 'Build',
    items: [
      { href: '/agents', label: 'My Agents', icon: Bot, permission: 'agents.read' },
      { href: '/builder', label: 'Agent Builder', icon: Sliders, permission: 'agents.write' },
      { href: '/widgets', label: 'Widgets', icon: Sparkles, permission: 'widgets.read' },  // <- new
    ],
  },
];
```

The `permission` string is checked against the result of `GET /api/me/permissions` — users without it don't see the sidebar item. If your page should be visible to everyone, omit `permission`.

---

## Backend endpoint

The frontend assumes `/api/widgets` exists. Add it to abenix-api or your standalone app:

```python
# apps/api/app/routers/widgets.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.deps import get_db, get_current_user
from app.core.responses import success
from models.user import User
from models.widget import Widget  # you've defined the model + migration

router = APIRouter(prefix="/api/widgets", tags=["widgets"])


@router.get("")
async def list_widgets(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Widget).where(Widget.tenant_id == user.tenant_id))
    return success([{"id": str(w.id), "name": w.name, "status": w.status} for w in q.scalars()])
```

Wire it in [`apps/api/app/main.py`](../../apps/api/app/main.py):
```python
from app.routers import widgets
app.include_router(widgets.router)
```

---

## Tests

### Backend (pytest)
```python
async def test_list_widgets(client, demo_tenant_user):
    r = await client.get("/api/widgets", headers=demo_tenant_user.headers)
    assert r.status_code == 200
    assert r.json()["data"] == []
```

### E2E (Playwright)
Add to `e2e/uat_audit_fixes.spec.ts` or create a focused spec:

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

If the page is user-facing, add a section to `/help` and capture a screenshot:

1. Add a section to `apps/web/src/app/(app)/help/page.tsx` (copy a sibling section as template).
2. Add a screenshot via the capture spec: `e2e/capture_audit_screenshots.spec.ts` — add a new test that opens your page + saves a PNG to `apps/web/public/docs-screenshots/`.

If the page is for developers, add a section here to `docs/05-ui/`.

---

## Common mistakes

| Mistake | Fix |
|---|---|
| Forgetting `'use client'` on a component with hooks | Add it at the top of the file |
| Using `useApi` for mutations | Use `apiFetch` directly — `useApi` is for cached GETs |
| `console.error` instead of `toastError` on failure | Always `toastError("Failed", e?.message)` |
| Hardcoding tailwind colours | Use the standard slate-900/800 background, slate-300 text palette |
| No empty state | Always render an `EmptyState` when the list is empty |
| Forgetting the sidebar entry | Add to `SIDEBAR_GROUPS` so the page is reachable |
| No mobile fallback | Test under 768px in DevTools. degrade to a simplified form |

---

## See also

- [05-ui/00-app-shell](../05-ui/00-app-shell.md) — layout + auth
- [05-ui/02-api-client](../05-ui/02-api-client.md) — apiFetch + error envelope
- [05-ui/03-page-catalogue](../05-ui/03-page-catalogue.md) — examples of mature pages
