import { expect, type Locator, type Page } from '@playwright/test';

// The sidebar opens in Essentials. A person who can't see a link opens Admin
// or presses "Show all tools" at the foot of the sidebar, and so do these helpers.

export function sidebarToggle(page: Page): Locator {
  return page.getByTestId('sidebar-mode-toggle').first();
}

// switch the sidebar mode with its own button and wait for the choice to be saved
export async function setSidebarMode(page: Page, mode: 'all' | 'essentials'): Promise<void> {
  const toggle = sidebarToggle(page);
  await expect(toggle).toBeVisible({ timeout: 20_000 });
  if ((await toggle.getAttribute('data-mode')) !== mode) {
    await expect(toggle).toHaveText(mode === 'all' ? 'Show all tools' : 'Show essentials only');
    const saved = page.waitForResponse((r) => r.url().includes('/api/me/ui-prefs') && r.request().method() === 'PUT');
    await toggle.click();
    expect((await saved).ok(), 'sidebar choice saved').toBe(true);
  }
  await expect(toggle).toHaveAttribute('data-mode', mode);
  await expect(page.getByTestId(mode === 'all' ? 'sidebar-all' : 'sidebar-essentials').first()).toBeVisible();
}

export async function showAllTools(page: Page): Promise<void> {
  await setSidebarMode(page, 'all');
}

// find a sidebar link by href, opening Admin or Show all tools only when Essentials hides it
export async function revealSidebarLink(page: Page, href: string): Promise<Locator> {
  const link = page.locator(`aside a[href="${href}"]`).first();
  await expect(sidebarToggle(page)).toBeVisible({ timeout: 20_000 });
  await link.waitFor({ state: 'attached', timeout: 3_000 }).catch(() => {});
  const admin = page.getByTestId('sidebar-admin-toggle').first();
  if (!(await link.count()) && (await admin.count()) && (await admin.getAttribute('aria-expanded')) === 'false') {
    await admin.click();
    await link.waitFor({ state: 'attached', timeout: 3_000 }).catch(() => {});
  }
  if (!(await link.count())) await setSidebarMode(page, 'all');
  await expect(link, `sidebar link to ${href}`).toBeAttached({ timeout: 20_000 });
  // its group may be folded away, open the group it sits in
  const folded = await link.evaluate((el) => !!el.closest('[class*="max-h-0"]')).catch(() => false);
  if (folded) {
    const group = link.locator('xpath=ancestor::div[.//button[@aria-expanded]][1]').locator('button[aria-expanded="false"]').first();
    if (await group.count()) await group.click();
  }
  await expect(link).toBeVisible();
  return link;
}

// open a page the way a person does, from its sidebar link
export async function openFromSidebar(page: Page, href: string): Promise<void> {
  // click scrolls the link into view itself and retries if the sidebar re-renders under it
  await (await revealSidebarLink(page, href)).click();
  await page.waitForURL((u) => u.pathname.startsWith(href), { timeout: 20_000 });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}
