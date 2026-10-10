/**
 * Knowledge projects and who sees what, driven through the UI as an admin and a second person.
 *
 *   1. Project       create one, define its ontology from the starter and an added type
 *   2. Collections   one open to project members, one private, one shared by link
 *   3. Members       add the second person, they see the project collection and not the private one
 *   4. Documents     restrict one document to the admin, give the other to the second person until a set time
 *   5. Grants        a collection grant and a share, both ending a few minutes out
 *   6. Expiry        once the time passes every one of those is refused, and the dialogs say expired
 *   7. Roles         Member sees the ontology read only, made Creator they can edit it, then put back
 *   8. Phone width   the same screens at 390px
 *
 * The API is only used to read state back and to clean up.
 *
 *   USE_K8S=true BASE=http://localhost:3100 API=http://localhost:8000 npx playwright test e2e/uat_sharing_depth_ui.spec.ts --workers=1
 */
import { test, expect, type Page } from '@playwright/test';
import * as path from 'path';
import {
  ADMIN, api, expectFitsPhone, expectReadable, go, inviteAndAccept, minutesAhead, nav, shooter, signIn,
} from './helpers/depth';

const RUN = Date.now().toString(36);
const shot = shooter(path.join(__dirname, 'uat_sharing_depth_ui'));
const PERSON = { email: `uat-share-${RUN}@example.com`, name: `Share Tester ${RUN}`, password: `ShareTest-${RUN}-9!` };
const PROJECT = `UAT Depth ${RUN}`;
const KB_OPEN = `Depth open ${RUN}`;
const KB_PRIVATE = `Depth private ${RUN}`;
const KB_SHARED = `Depth shared ${RUN}`;
const DOC_PUBLIC = `harbour-hours-${RUN}.txt`;
const DOC_SECRET = `harbour-codes-${RUN}.txt`;

const ids: { project?: string; kbs: Record<string, string>; userId?: string } = { kbs: {} };

test.use({ viewport: { width: 1440, height: 900 } });

function txt(name: string, body: string) {
  return { name, mimeType: 'text/plain', buffer: Buffer.from(body) };
}

async function openProject(page: Page) {
  if (!page.url().includes('/knowledge/projects') || page.url().includes('/ontology')) {
    await go(page, '/knowledge');
    await page.getByRole('link', { name: 'Projects' }).first().click();
    await page.waitForURL(/\/knowledge\/projects$/);
  }
  const row = page.locator('div.rounded-xl').filter({ has: page.getByText(PROJECT, { exact: true }) }).first();
  await expect(row).toBeVisible({ timeout: 20_000 });
  if (!(await row.getByTestId('kp-collection').count()) && !(await row.getByTestId('kp-add-kb').count())) {
    await row.getByText(PROJECT, { exact: true }).click();
  }
  return row;
}

// create a knowledge base inside the project from its own link, then upload files
async function createKb(page: Page, name: string, visibility: 'project' | 'private', files: ReturnType<typeof txt>[]) {
  const row = await openProject(page);
  await row.getByTestId('kp-add-kb').first().click();
  await page.waitForURL(/\/knowledge\?new=1&project=/);
  await expect(page.locator('#kb-new-project')).toHaveValue(ids.project!, { timeout: 20_000 });
  await page.locator('#kb-new-name').fill(name);
  await page.locator('#kb-new-description').fill(`Depth spec ${visibility} collection`);
  await page.locator('#kb-new-visibility').selectOption(visibility);
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/knowledge\?id=/, { timeout: 30_000 });
  ids.kbs[name] = new URL(page.url()).searchParams.get('id')!;
  if (files.length) {
    await page.getByTestId('kb-dropzone-input').setInputFiles(files);
    for (const f of files) {
      await expect(page.locator(`[data-testid="kb-doc-row"][data-name="${f.name}"]`)).toHaveAttribute('data-status', 'ready', { timeout: 180_000 });
    }
  }
}

async function docRow(page: Page, name: string) {
  return page.locator(`[data-testid="kb-doc-row"][data-name="${name}"]`);
}

test('projects, ontology, members, document and collection grants, shares that expire, roles', async ({ page, browser }) => {
  test.setTimeout(30 * 60_000);
  page.on('dialog', (d) => d.accept());
  await signIn(page);

  const { ctx, p: other, userId } = await inviteAndAccept(page, browser, PERSON);
  ids.userId = userId;

  try {
    await test.step('create a project and define its ontology', async () => {
      await nav(page, '/knowledge');
      await page.getByRole('link', { name: 'Projects' }).first().click();
      await page.waitForURL(/\/knowledge\/projects$/);
      await page.getByRole('button', { name: 'New Project' }).first().click();
      await page.getByPlaceholder('e.g. Legal Knowledge').fill(PROJECT);
      await page.getByPlaceholder("What's this project for?").fill('Harbour operations used by the depth spec.');
      await page.getByRole('button', { name: 'Create Project' }).click();
      await expect(page.getByTestId('kp-next-steps')).toBeVisible({ timeout: 20_000 });
      const projects = (await api(page, 'GET', '/api/knowledge-projects?limit=100')).json.data as any[];
      ids.project = projects.find((p) => p.name === PROJECT).id;
      await shot(page, '01-project-created');

      await page.getByTestId('kp-next-steps').getByText('Define its ontology').click();
      await page.waitForURL(/\/ontology$/);
      await page.getByRole('button', { name: /Insert starter/ }).click();
      await page.getByTestId('onto-name').fill(`Harbour v1 ${RUN}`);
      await page.getByTestId('onto-add-entity').click();
      const added = page.getByTestId('onto-entity').last();
      await added.getByTestId('onto-entity-name').fill('Berth');
      await added.getByLabel('Entity type description').fill('A numbered mooring place in the harbour');
      await page.getByTestId('onto-add-rel').click();
      const rel = page.getByTestId('onto-rel').last();
      await rel.getByTestId('onto-rel-name').fill('docks at');
      await rel.getByLabel('Relationship description').fill('Counterparty vessel docks at a Berth');
      await rel.getByTestId('onto-rel-from').fill('Counterparty');
      await rel.getByTestId('onto-rel-to').fill('Berth');
      await page.getByTestId('onto-save').click();
      await expect(page.getByText('Saved as version 1')).toBeVisible({ timeout: 20_000 });
      const active = (await api(page, 'GET', `/api/knowledge-projects/${ids.project}/ontology-schemas/active`)).json.data;
      expect(active.entity_types.map((e: any) => e.name)).toEqual(expect.arrayContaining(['Counterparty', 'Corridor', 'Regulation', 'Berth']));
      expect(active.relationship_types.map((r: any) => r.name)).toContain('DOCKS_AT');
      await expectReadable(page);
      await shot(page, '02-ontology-saved');
    });

    await test.step('three collections in the project: open to members, private, shared', async () => {
      await createKb(page, KB_OPEN, 'project', [
        txt(DOC_PUBLIC, `The harbour office ${RUN} opens at 07:30 and closes at 18:00 on weekdays.`),
        txt(DOC_SECRET, `The gate code for berth 9 (${RUN}) is 4471.`),
      ]);
      await shot(page, '03-kb-open');
      await createKb(page, KB_PRIVATE, 'private', [txt(`private-${RUN}.txt`, `Private harbour budget notes ${RUN}.`)]);
      await createKb(page, KB_SHARED, 'private', []);
      const row = await openProject(page);
      await expect(row.getByTestId('kp-collection')).toHaveCount(3, { timeout: 20_000 });
    });

    await test.step('add the second person as a project member', async () => {
      await go(page, '/knowledge/projects');
      const row = await openProject(page);
      await row.getByTestId('kp-members').click();
      const modal = page.getByTestId('project-members-modal');
      await modal.getByTestId('member-subject').selectOption({ label: `${PERSON.name} · ${PERSON.email}` });
      await expect(modal.getByText(/Can read the knowledge bases in this project/)).toBeVisible();
      await modal.getByTestId('member-submit').click();
      await expect(modal.locator(`[data-testid="member-row"][data-subject="${ids.userId}"]`)).toContainText('VIEW', { timeout: 20_000 });
      await shot(page, '04-member-added');
      await page.keyboard.press('Escape');

      await expect(async () => {
        await go(other, '/knowledge');
        await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_OPEN}"]`)).toBeVisible({ timeout: 10_000 });
      }).toPass({ timeout: 90_000 });
      await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_PRIVATE}"]`)).toHaveCount(0);
      await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_SHARED}"]`)).toHaveCount(0);
    });

    const ends = minutesAhead(2);

    await test.step('restrict one document to the admin and give the other to the second person until a set time', async () => {
      await go(page, `/knowledge?id=${ids.kbs[KB_OPEN]}`);
      await (await docRow(page, DOC_SECRET)).getByTestId('kb-doc-access').click();
      let modal = page.getByTestId('doc-access-modal');
      await expect(modal.getByTestId('doc-access-state')).toContainText('Open to everyone');
      await modal.getByTestId('doc-grant-subject').selectOption({ label: 'Admin User · admin@abenix.dev' }).catch(async () => {
        await modal.getByTestId('doc-grant-subject').selectOption({ index: 1 });
      });
      await modal.getByTestId('doc-grant-submit').click();
      await expect(modal.getByTestId('doc-access-state')).toContainText('Restricted', { timeout: 20_000 });
      await page.keyboard.press('Escape');

      await (await docRow(page, DOC_PUBLIC)).getByTestId('kb-doc-access').click();
      modal = page.getByTestId('doc-access-modal');
      await modal.getByTestId('doc-grant-subject').selectOption({ label: `${PERSON.name} · ${PERSON.email}` });
      await modal.getByTestId('doc-grant-expiry').fill(ends.input);
      await modal.getByTestId('doc-grant-submit').click();
      const grant = modal.locator(`[data-testid="doc-grant-row"][data-subject="${ids.userId}"]`);
      await expect(grant.getByTestId('share-expires')).toContainText('expires on', { timeout: 20_000 });
      await shot(page, '05-doc-grant-expiring');
      await page.keyboard.press('Escape');

      await go(other, `/knowledge?id=${ids.kbs[KB_OPEN]}`);
      await expect(await docRow(other, DOC_PUBLIC)).toBeVisible({ timeout: 20_000 });
      await expect(await docRow(other, DOC_SECRET)).toHaveCount(0);
      // a member who can only read gets no sharing controls on documents
      await expect(other.getByTestId('kb-doc-access')).toHaveCount(0);
      await shot(other, '06-member-sees-one-doc');
    });

    await test.step('a collection grant and a share, both ending at the same time', async () => {
      await go(page, '/knowledge/projects');
      const row = await openProject(page);
      await row.locator(`[data-testid="kp-collection"][data-name="${KB_PRIVATE}"]`).getByTestId('kp-access').click();
      const modal = page.getByTestId('collection-grants-modal');
      await modal.getByTestId('grant-subject').selectOption({ label: `${PERSON.name} · ${PERSON.email}` });
      await modal.getByTestId('grant-permission').selectOption('READ');
      await modal.getByTestId('grant-expiry').fill(ends.input);
      await modal.getByTestId('grant-submit').click();
      const g = modal.locator(`[data-testid="grant-row"][data-subject="${ids.userId}"]`);
      await expect(g).toContainText(PERSON.email, { timeout: 20_000 });
      await expect(g.getByTestId('share-expires')).toBeVisible();
      await shot(page, '07-collection-grant-expiring');
      await page.keyboard.press('Escape');

      await go(page, `/knowledge?id=${ids.kbs[KB_SHARED]}`);
      await page.getByTestId('kb-share').click();
      const dlg = page.getByTestId('resource-share-dialog');
      await dlg.getByTestId('share-email-input').fill(PERSON.email);
      await dlg.getByTestId('share-permission-select').selectOption('view');
      await dlg.getByTestId('share-expiry-input').fill(ends.input);
      await dlg.getByTestId('share-submit').click();
      const s = dlg.locator(`[data-email="${PERSON.email}"]`);
      await expect(s.getByTestId('share-expires')).toContainText('expires on', { timeout: 20_000 });
      await shot(page, '08-share-expiring');
      await dlg.getByRole('button', { name: 'Close' }).click();

      await go(other, '/knowledge');
      await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_PRIVATE}"]`)).toBeVisible({ timeout: 20_000 });
      await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_SHARED}"]`)).toBeVisible();
      await shot(other, '09-member-sees-granted');
    });

    await test.step('a Member sees the ontology read only, made Creator they can edit it', async () => {
      await go(other, `/knowledge/projects/${ids.project}/ontology`);
      await expect(other.getByText('You can view the current ontology but not edit it.')).toBeVisible({ timeout: 20_000 });
      await expect(other.getByText('Berth', { exact: true })).toBeVisible();

      await nav(page, '/admin/rbac');
      await page.getByTestId('rbac-filter').fill(PERSON.email);
      const select = page.getByTestId(`rbac-role-${PERSON.email}`);
      await expect(select).toHaveValue('user', { timeout: 20_000 });
      await select.selectOption('creator');
      await expect(page.getByRole('dialog')).toContainText('Edit ontologies');
      await shot(page, '10-rbac-confirm');
      await page.getByTestId('rbac-role-confirm').click();
      await expect(page.getByTestId('rbac-notice')).toContainText('is now Creator', { timeout: 20_000 });
      expect((await api(other, 'GET', '/api/me/permissions')).json.data.features.manage_ontology).toBe(true);

      await other.reload({ waitUntil: 'domcontentloaded' });
      await expect(other.getByTestId('onto-save')).toBeVisible({ timeout: 20_000 });
      await shot(other, '11-creator-edits-ontology');

      await page.getByTestId(`rbac-role-${PERSON.email}`).selectOption('user');
      await page.getByTestId('rbac-role-confirm').click();
      await expect(page.getByTestId('rbac-notice')).toContainText('is now Member', { timeout: 20_000 });
      await other.reload({ waitUntil: 'domcontentloaded' });
      await expect(other.getByText('You can view the current ontology but not edit it.')).toBeVisible({ timeout: 20_000 });
    });

    await test.step('after the end time every grant and share is refused', async () => {
      const wait = ends.at - Date.now() + 5_000;
      if (wait > 0) await page.waitForTimeout(wait);

      await go(other, `/knowledge?id=${ids.kbs[KB_OPEN]}`);
      await expect(other.locator('[data-testid="kb-doc-row"]').first()).toBeVisible({ timeout: 20_000 }).catch(() => {});
      // the lapsed grant keeps the document restricted rather than opening it to everyone
      await expect(await docRow(other, DOC_PUBLIC)).toHaveCount(0);
      await expect(await docRow(other, DOC_SECRET)).toHaveCount(0);

      await expect(async () => {
        await go(other, '/knowledge');
        await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_OPEN}"]`)).toBeVisible({ timeout: 10_000 });
      }).toPass({ timeout: 90_000 });
      await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_PRIVATE}"]`)).toHaveCount(0);
      await expect(other.locator(`[data-testid="kb-card"][data-name="${KB_SHARED}"]`)).toHaveCount(0);
      expect((await api(other, 'GET', `/api/knowledge-bases/${ids.kbs[KB_PRIVATE]}`)).status).toBe(404);
      expect((await api(other, 'GET', `/api/knowledge-bases/${ids.kbs[KB_SHARED]}`)).status).toBe(404);
      await shot(other, '12-member-after-expiry');

      // the owner sees them marked expired
      await go(page, `/knowledge?id=${ids.kbs[KB_SHARED]}`);
      await page.getByTestId('kb-share').click();
      await expect(page.getByTestId('resource-share-dialog').locator(`[data-email="${PERSON.email}"]`).getByTestId('share-expired')).toBeVisible({ timeout: 20_000 });
      await shot(page, '13-share-expired');
      await page.getByTestId('resource-share-dialog').getByRole('button', { name: 'Close' }).click();

      await go(page, '/knowledge/projects');
      const row = await openProject(page);
      await row.locator(`[data-testid="kp-collection"][data-name="${KB_PRIVATE}"]`).getByTestId('kp-access').click();
      await expect(page.getByTestId('collection-grants-modal').locator(`[data-testid="grant-row"][data-subject="${ids.userId}"]`).getByTestId('share-expired')).toBeVisible({ timeout: 20_000 });
      await page.keyboard.press('Escape');

      await go(page, `/knowledge?id=${ids.kbs[KB_OPEN]}`);
      await (await docRow(page, DOC_PUBLIC)).getByTestId('kb-doc-access').click();
      const dm = page.getByTestId('doc-access-modal');
      await expect(dm.getByTestId('share-expired')).toBeVisible({ timeout: 20_000 });
      await expect(dm.getByTestId('doc-access-state')).toContainText('Restricted');
      await shot(page, '14-doc-grant-expired');
      await page.keyboard.press('Escape');
    });

    await test.step('phone width', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      for (const route of ['/knowledge/projects', `/knowledge/projects/${ids.project}/ontology`, `/knowledge?id=${ids.kbs[KB_OPEN]}`, '/admin/rbac']) {
        await go(page, route);
        await page.waitForTimeout(800);
        await expectFitsPhone(page, route);
      }
      await go(page, '/knowledge/projects');
      const row = await openProject(page);
      await row.getByTestId('kp-members').click();
      await expectFitsPhone(page, 'members modal');
      await shot(page, '15-phone-members');
      await page.keyboard.press('Escape');
      await go(page, `/knowledge?id=${ids.kbs[KB_OPEN]}`);
      await (await docRow(page, DOC_SECRET)).getByTestId('kb-doc-access').click();
      await expectFitsPhone(page, 'document access modal');
      await shot(page, '16-phone-doc-access');
      await page.keyboard.press('Escape');
      await go(page, '/admin/rbac');
      await shot(page, '17-phone-rbac');
      await page.setViewportSize({ width: 1440, height: 900 });
    });
  } finally {
    await ctx.close();
  }
});

test.afterAll(async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await signIn(page, ADMIN);
  for (const id of Object.values(ids.kbs)) await api(page, 'DELETE', `/api/knowledge-bases/${id}?force=true`);
  if (ids.project) await api(page, 'DELETE', `/api/knowledge-projects/${ids.project}`);
  if (ids.userId) await api(page, 'DELETE', `/api/team/members/${ids.userId}`);
  await ctx.close();
});
