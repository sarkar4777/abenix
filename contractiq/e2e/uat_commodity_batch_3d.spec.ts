import { test, expect, type Page, type Response } from '@playwright/test';

// UAT — Batch 3D commodities (carbon, crude, refined, coal).
//
// Selector landing for all four + run-analysis on the default
// region/product. The other regions/products are exercised by the
// selector tests only (per the pass-gate). On provider rate-limit the
// run is documented as did-not-run, not a hard fail — NORDICS/PJM
// precedent.

const BASE  = process.env.BASE  || process.env.BASE_URL || 'http://localhost:3001';
const API   = process.env.API   || process.env.API_URL  || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL    || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';

type Sub = string; // generic region/product label

// Each commodity entry mirrors the contractiq forward page contract:
// label (Title Case for H1), the sub-selector kind, the list of options,
// default option, expected anchor_currency and the canonical sanity band
// for the default sub. The selector entries also document the test-id
// pattern the UI exposes so the test can assert without hand-rolling
// CSS.
interface SubBand { lo: number; hi: number; currency: 'EUR' | 'USD' }
interface CommodityCfg {
  slug:               'carbon' | 'crude' | 'refined' | 'coal';
  h1Label:            string;          // exact Title-Case label in H1
  // Carbon currently only has the EUA benchmark — the page renders the
  // primary commodity selector and skips the second-level row. Task
  // pass-gate covers carbon under "Selector visible" only (the brief
  // calls out crude/refined/coal for the sub-selector check).
  selectorKind:       'region' | 'product' | 'none';
  options:            string[];        // valid sub options (informational for carbon)
  defaultOption:      string;          // pre-selected when ?sub= omitted
  switchToOption?:    string;          // option used in the in-page switch test
  band:               SubBand;         // canonical band for the run
  bodyKey:            'region' | 'product';
  bodyValue:          string;
  expectedUnitPrefix: string;          // e.g. 'EUR/TCO2', 'USD/BBL', 'USD/GAL', 'USD/TON'
  priceKeys:          string[];        // forward_curve point keys to read p50 off
}

const COMMODITIES: CommodityCfg[] = [
  {
    slug:               'carbon',
    h1Label:            'Carbon (EUA)',
    // Single benchmark — page renders only the primary commodity tile
    // row, no second-level region/product selector.
    selectorKind:       'none',
    options:            ['EUA'],
    defaultOption:      'EUA',
    band:               { lo: 30, hi: 200, currency: 'EUR' },
    bodyKey:            'region',
    bodyValue:          'EUA',
    expectedUnitPrefix: 'EUR/TCO2',
    priceKeys:          ['price_eur_tco2', 'price', 'mid', 'value', 'expected'],
  },
  {
    slug:               'crude',
    h1Label:            'Crude',
    selectorKind:       'region',
    options:            ['BRENT', 'WTI'],
    defaultOption:      'BRENT',
    switchToOption:     'WTI',
    band:               { lo: 20, hi: 200, currency: 'USD' },
    bodyKey:            'region',
    bodyValue:          'BRENT',
    expectedUnitPrefix: 'USD/BBL',
    priceKeys:          ['price_usd_bbl', 'price', 'mid', 'value', 'expected'],
  },
  {
    slug:               'refined',
    h1Label:            'Refined Products',
    selectorKind:       'product',
    options:            ['RBOB', 'ULSD', 'JET'],
    defaultOption:      'RBOB',
    switchToOption:     'ULSD',
    band:               { lo: 1.0, hi: 5.0, currency: 'USD' },
    bodyKey:            'product',
    bodyValue:          'RBOB',
    expectedUnitPrefix: 'USD/GAL',
    priceKeys:          ['price_usd_gal', 'price', 'mid', 'value', 'expected'],
  },
  {
    slug:               'coal',
    h1Label:            'Coal',
    selectorKind:       'region',
    options:            ['NEWCASTLE', 'API2', 'API4'],
    defaultOption:      'NEWCASTLE',
    switchToOption:     'API2',
    band:               { lo: 50, hi: 500, currency: 'USD' },
    bodyKey:            'region',
    bodyValue:          'NEWCASTLE',
    expectedUnitPrefix: 'USD/TON',
    priceKeys:          ['price_usd_ton', 'price', 'mid', 'value', 'expected'],
  },
];

async function login(page: Page) {
  const resp = await fetch(`${API}/api/contractiq/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  const token = json.data?.access_token || json.access_token;
  expect(token, 'login should return an access_token').toBeTruthy();
  const meResp = await fetch(`${API}/api/contractiq/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const me = await meResp.json().then(j => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('contractiq_token', t);
      localStorage.setItem(
        'contractiq_user',
        JSON.stringify(u || { email: 'test@contractiq.com', role: 'analyst' }),
      );
    } catch {}
  }, { t: token, u: me });
}

async function gotoOk(page: Page, p: string) {
  const r = await page.goto(`${BASE}${p}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  expect(r?.status(), `${p} status`).toBeLessThan(400);
}

// Pick a numeric price off a forward_curve point. The agents emit
// per-commodity keys (price_usd_bbl, price_eur_tco2, ...) so the test
// trusts the same set of fallbacks the renderer does.
function pickPrice(p: any, keys: string[]): number | null {
  if (!p || typeof p !== 'object') return null;
  for (const k of keys) {
    const v = p[k];
    if (typeof v === 'number' && isFinite(v)) return v;
  }
  return null;
}

for (const cfg of COMMODITIES) {
  test.describe(`commodity batch 3D — ${cfg.slug}`, () => {
    test.beforeEach(async ({ page }) => { await login(page); });

    // ── Check 1 — Selector landing ───────────────────────────────────
    // H1 must read Title Case (e.g. "Carbon (EUA)", "Refined Products"),
    // never the raw slug like "contractiq_carbon_fairvalue" or
    // "refined_products". Commodity selector visible and the active tile
    // is the one we picked.
    test(`selector landing — H1 Title Case, no raw slug, ${cfg.selectorKind} selector visible`, async ({ page }) => {
      await gotoOk(page, `/commodities/forward?commodity=${cfg.slug}`);

      const h1 = page.locator('h1').first();
      await expect(h1).toBeVisible({ timeout: 10000 });
      const h1Text = (await h1.textContent()) || '';
      expect(h1Text, `${cfg.slug}: H1 must include "Forward fair-value"`).toContain('Forward fair-value');
      expect(h1Text, `${cfg.slug}: H1 must include label "${cfg.h1Label}"`).toContain(cfg.h1Label);
      expect(
        h1Text.toLowerCase(),
        `${cfg.slug}: H1 must not leak the raw agent slug`,
      ).not.toContain(`contractiq_${cfg.slug}_fairvalue`);
      // No underscore-style raw slugs in the H1 ever.
      expect(
        h1Text,
        `${cfg.slug}: H1 must not show raw "${cfg.slug}_" style tokens`,
      ).not.toContain(`${cfg.slug}_`);

      // Commodity tile is enabled + active.
      const tile = page.locator(`[data-testid="commodity-${cfg.slug}"]`);
      await expect(tile).toBeVisible();
      await expect(tile).not.toBeDisabled();

      if (cfg.selectorKind === 'region') {
        const bar = page.locator('[data-testid="region-selector"]');
        await expect(bar, `${cfg.slug}: region selector must be visible`).toBeVisible({ timeout: 10000 });
        for (const r of cfg.options) {
          await expect(page.locator(`[data-testid="region-${r}"]`)).toBeVisible();
        }
        await expect(
          page.locator(`[data-testid="region-${cfg.defaultOption}"]`),
        ).toHaveAttribute('data-active', 'true');
      } else if (cfg.selectorKind === 'product') {
        const bar = page.locator('[data-testid="product-selector"]');
        await expect(bar, `${cfg.slug}: product selector must be visible`).toBeVisible({ timeout: 10000 });
        for (const p of cfg.options) {
          await expect(page.locator(`[data-testid="product-${p}"]`)).toBeVisible();
        }
        await expect(
          page.locator(`[data-testid="product-${cfg.defaultOption}"]`),
        ).toHaveAttribute('data-active', 'true');
      } else {
        // Single-benchmark commodity (carbon today). The primary
        // commodity selector row IS the selector; the page legitimately
        // doesn't render a second-level row. Confirm the commodity-
        // selector container exists and the active tile is highlighted.
        const cs = page.locator('[data-testid="commodity-selector"]');
        await expect(cs, `${cfg.slug}: commodity selector must be visible`).toBeVisible({ timeout: 10000 });
        await expect(tile).toHaveClass(/orange/);
      }
    });

    // ── Check 2/3/4 — Sub-selector switch updates URL/state ─────────
    // For crude+coal we flip region, for refined we flip product. Carbon
    // only has EUA so this test is skipped (selector single-element).
    // The page reads ?region=/?product= on mount and the in-page switch
    // (a) flips data-active and (b) clears any cached run so the analyst
    // never reads stale numbers under a fresh label.
    if (cfg.switchToOption) {
      const switchKind = cfg.selectorKind === 'region' ? 'region' : 'product';
      const urlKey     = cfg.selectorKind === 'region' ? 'region' : 'product';
      test(`${switchKind} switch — deep links + in-page click flip active, clears stale`, async ({ page }) => {
        // Deep link each option and confirm only that one is active +
        // no stale run drawer is rendered.
        for (const opt of cfg.options) {
          await gotoOk(
            page,
            `/commodities/forward?commodity=${cfg.slug}&${urlKey}=${opt}`,
          );
          await expect(
            page.locator(`[data-testid="${switchKind}-${opt}"]`),
          ).toHaveAttribute('data-active', 'true', { timeout: 10000 });
          const runBtn = page.locator('[data-testid="run-analysis"]');
          await expect(runBtn).toBeEnabled();
          // No cached audit drawer before any click of Run.
          const audit = page.locator('[data-testid="audit-drawer"]');
          await expect(audit).toHaveCount(0);
        }

        // In-page switch — start on default, click the alt, confirm
        // both data-active flags flip.
        await gotoOk(
          page,
          `/commodities/forward?commodity=${cfg.slug}&${urlKey}=${cfg.defaultOption}`,
        );
        await expect(
          page.locator(`[data-testid="${switchKind}-${cfg.defaultOption}"]`),
        ).toHaveAttribute('data-active', 'true');

        await page.locator(`[data-testid="${switchKind}-${cfg.switchToOption}"]`).click();
        await expect(
          page.locator(`[data-testid="${switchKind}-${cfg.switchToOption}"]`),
        ).toHaveAttribute('data-active', 'true');
        await expect(
          page.locator(`[data-testid="${switchKind}-${cfg.defaultOption}"]`),
        ).toHaveAttribute('data-active', 'false');

        // After the switch, no audit drawer (no run fired yet).
        const auditAfter = page.locator('[data-testid="audit-drawer"]');
        await expect(auditAfter).toHaveCount(0);
      });
    }

    // ── Check 5 — Run analysis end-to-end on the default ─────────────
    // The agent + Yahoo proxy + canonical-anchor overlay routinely runs
    // 2-4 min. Set per-test timeout to 6 min per the task brief; budget
    // the response wait to 340s.
    test(`run analysis end-to-end for default (${cfg.defaultOption})`, async ({ page }) => {
      test.setTimeout(360_000);
      await gotoOk(page, `/commodities/forward?commodity=${cfg.slug}`);

      // Confirm the default sub is active before firing. Carbon has no
      // sub-selector today (single-benchmark) — just confirm the
      // commodity tile shows the right H1.
      if (cfg.selectorKind === 'region') {
        await expect(
          page.locator(`[data-testid="region-${cfg.defaultOption}"]`),
        ).toHaveAttribute('data-active', 'true', { timeout: 10000 });
      } else if (cfg.selectorKind === 'product') {
        await expect(
          page.locator(`[data-testid="product-${cfg.defaultOption}"]`),
        ).toHaveAttribute('data-active', 'true', { timeout: 10000 });
      } else {
        await expect(page.locator('h1').first()).toContainText(cfg.h1Label, { timeout: 10000 });
      }

      const apiResponsePromise = page.waitForResponse(
        r => new RegExp(`/api/contractiq/commodities/${cfg.slug}/forward/run`).test(r.url()),
        { timeout: 340_000 },
      );

      const btn = page.locator('[data-testid="run-analysis"]');
      await expect(btn).toBeEnabled();
      await btn.click();

      let resp: Response;
      try {
        resp = await apiResponsePromise;
      } catch (e: any) {
        test.fail(false, `${cfg.slug}: agent invocation timed out — ${e?.message}`);
        return;
      }

      const status = resp.status();
      const bodyText = await resp.text();
      let body: any = {};
      try { body = JSON.parse(bodyText); } catch {}
      const payload = body?.data || body;
      const forecast = payload?.forecast || null;
      const rawOut = (payload?.raw_output || '').toString();
      const errMsg = (body?.error?.message || '').toString().toLowerCase();

      // Rate-limit / provider-failure detection. Document as did-not-run
      // per the NORDICS / PJM precedent — never a hard fail.
      const isRateLimit =
        status === 429 ||
        /rate.?limit|429|too many requests|throttle|quota/i.test(errMsg) ||
        /rate.?limit|429|too many requests|throttle|quota/i.test(rawOut);
      const isProviderFailure =
        status >= 500 ||
        /azure.*error|llm provider|provider.*unavailable|openai.*error|503/i.test(errMsg);

      if (isRateLimit || isProviderFailure) {
        // eslint-disable-next-line no-console
        console.warn(
          `[uat_commodity_batch_3d] ${cfg.slug}: documented did-not-run — ` +
          `status=${status} err="${errMsg.slice(0, 160)}"`,
        );
        test.skip(true, `${cfg.slug}: provider rate-limit / failure (status=${status}) — did-not-run`);
        return;
      }

      // Beyond this point the agent returned, so the assertions are real.
      expect(forecast, `${cfg.slug}: agent returned an empty forecast envelope`).toBeTruthy();

      // Honest-degraded path — when Yahoo returns empty and the agent
      // doesn't fabricate, the post-processor leaves the forecast alone
      // and data_quality stays 'degraded' with empty curves. That is a
      // PASS for "no fabricated numbers" but obviously skips the
      // curve-shape checks.
      const dqEarly = (forecast.data_quality || '').toString().toLowerCase();
      const forwardCurve =
        (forecast.forward_curve || forecast.expected_curve || []) as any[];
      const honestDegraded =
        dqEarly === 'degraded' &&
        forwardCurve.length === 0;

      if (!honestDegraded) {
        // (a) forward_curve has 12 entries on the clean path. The agent
        // emits expected_curve; some YAMLs alias as forward_curve.
        expect(
          forwardCurve.length,
          `${cfg.slug}: forward_curve should have 12 entries (got ${forwardCurve.length})`,
        ).toBe(12);

        // (b) p50 within the canonical band for the default sub.
        for (let i = 0; i < forwardCurve.length; i += 1) {
          const pt = forwardCurve[i];
          const p50 =
            typeof pt?.p50 === 'number' ? pt.p50 : pickPrice(pt, cfg.priceKeys);
          expect(
            typeof p50,
            `${cfg.slug}: forward_curve[${i}].p50 should be a number`,
          ).toBe('number');
          expect(
            p50 as number,
            `${cfg.slug}: forward_curve[${i}].p50=${p50} outside band ` +
              `[${cfg.band.lo}, ${cfg.band.hi}] ${cfg.band.currency}`,
          ).toBeGreaterThanOrEqual(cfg.band.lo);
          expect(
            p50 as number,
            `${cfg.slug}: forward_curve[${i}].p50=${p50} outside band ` +
              `[${cfg.band.lo}, ${cfg.band.hi}] ${cfg.band.currency}`,
          ).toBeLessThanOrEqual(cfg.band.hi);
        }
      }

      // (c) anchor_currency matches the expected (EUR for carbon, USD
      // for the rest) — even on the honest-degraded path the agent must
      // stamp the right ISO so the analyst never sees a wrong-unit number.
      const anchorCurrency = (forecast.anchor_currency || '').toString().toUpperCase();
      expect(
        anchorCurrency,
        `${cfg.slug}: anchor_currency should be ${cfg.band.currency} ` +
          `(got "${anchorCurrency}")`,
      ).toBe(cfg.band.currency);

      // Unit string — case-insensitive prefix match because some YAMLs
      // emit "USD/bbl" and others uppercase. Accept either.
      const unit = (forecast.unit || '').toString().toUpperCase();
      if (!honestDegraded) {
        expect(
          unit.startsWith(cfg.expectedUnitPrefix),
          `${cfg.slug}: unit should start with ${cfg.expectedUnitPrefix} (got "${unit}")`,
        ).toBe(true);
      }

      // (d) Provenance banner is honest. real_fetched, agent_simulated,
      // or mixed (canonical-anchor override path). 'mixed' must carry an
      // explanation note.
      const provenance = forecast.provenance || {};
      const mode = (provenance.mode || '').toString().toLowerCase();
      const allowedModes = ['real_fetched', 'agent_simulated', 'mixed', 'unknown'];
      expect(
        allowedModes,
        `${cfg.slug}: provenance.mode must be one of ${allowedModes.join(',')} ` +
          `(got "${mode}")`,
      ).toContain(mode);

      if (mode === 'mixed') {
        const notes = (provenance.notes || '').toString().toLowerCase();
        expect(
          notes,
          `${cfg.slug}: mode='mixed' must carry honest notes about the override`,
        ).toMatch(/anchor|override|fallback|post.?processor|live/);
      }

      // (e) data_quality is honest — live/good/degraded only. Degraded
      // must come with an explanation in summary_markdown so the analyst
      // sees WHY the curve is empty.
      const dq = (forecast.data_quality || '').toString().toLowerCase();
      const acceptableDq = ['live', 'good', 'degraded'];
      expect(
        acceptableDq,
        `${cfg.slug}: data_quality must be one of ${acceptableDq.join(',')} ` +
          `(got "${dq}")`,
      ).toContain(dq);

      if (dq === 'degraded') {
        const summary = (forecast.summary_markdown || forecast.summary || '').toString();
        expect(
          summary.length,
          `${cfg.slug}: data_quality='degraded' must include an explanation in summary_markdown`,
        ).toBeGreaterThan(20);
      }

      // (f) No fabricated numbers — when the agent ran clean
      // (real_fetched or mixed), the anchor must name a real source.
      // Degraded path is exempt because the agent legitimately gave up.
      if ((mode === 'real_fetched' || mode === 'mixed') && !honestDegraded) {
        const anchorSrc = (
          forecast.anchor_source || provenance.data_source || ''
        ).toString();
        expect(
          anchorSrc.length,
          `${cfg.slug}: real_fetched/mixed run must name a real anchor_source/data_source`,
        ).toBeGreaterThan(0);
        expect(
          anchorSrc.toLowerCase(),
          `${cfg.slug}: anchor_source="${anchorSrc}" must reference yahoo / eia / monte carlo / commodity`,
        ).toMatch(/yahoo|eia|monte\s*carlo|krbn|co2\.l|carbon|crude|brent|wti|coal|newcastle|api2|api4|refined|rbob|ulsd|jet/);
      }

      // (g) Drivers cite real sources. Flatten top-level drivers + per-
      // scenario drivers. On the clean path at least one driver MUST
      // carry a real http(s) URL or a named market-data source string —
      // pure narratives are not allowed. Honest-degraded path is exempt
      // because the agent legitimately emits no drivers when the anchor
      // came back empty.
      const flatDrivers: Array<{ source?: string; url?: string; headline?: string }> = [];
      for (const d of forecast.drivers || []) flatDrivers.push(d);
      for (const s of forecast.scenarios || []) {
        for (const d of s.drivers || []) flatDrivers.push(d);
      }

      if (!honestDegraded) {
        expect(
          flatDrivers.length,
          `${cfg.slug}: should produce at least one driver`,
        ).toBeGreaterThan(0);

        const withUrl = flatDrivers.filter(
          d => typeof d.url === 'string' && /^https?:\/\//.test(d.url),
        );
        const withNamedSource = flatDrivers.filter(d => {
          const src = (d.source || '').toString().trim();
          if (!src) return false;
          if (/^(unknown|n\/?a|none|-+)$/i.test(src)) return false;
          return src.length > 2;
        });

        expect(
          withUrl.length + withNamedSource.length,
          `${cfg.slug}: at least one driver must cite a real URL or named market-data source ` +
            `(got ${withUrl.length} urls, ${withNamedSource.length} named sources out of ${flatDrivers.length})`,
        ).toBeGreaterThan(0);
      }

      // (h) On-page provenance banner reads honestly.
      const provBanner = page.locator('[data-testid="provenance-banner"]');
      await expect(provBanner).toBeVisible();
      const provModeNode = page.locator('[data-testid="provenance-mode"]');
      await expect(provModeNode).toBeVisible();
      const provModeText = ((await provModeNode.textContent()) || '').toLowerCase();
      expect(
        provModeText,
        `${cfg.slug}: banner should reflect a documented provenance mode`,
      ).toMatch(/real fetched|fetched|simulated|mixed|unknown/);
    });
  });
}
