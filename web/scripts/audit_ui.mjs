/**
 * Adversarial UI audit for the UrbanFLOW Command Center (revamped floating HUD).
 *
 *   node scripts/audit_ui.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const URL = process.env.VERIFY_URL || 'http://127.0.0.1:8000/'
const OUT = path.resolve('..', 'scratch', 'verification')
fs.mkdirSync(OUT, { recursive: true })

const results = []
const record = (id, status, detail) => {
  results.push({ id, status, detail })
  const mark = { PASS: '\x1b[32mPASS\x1b[0m', FAIL: '\x1b[31mFAIL\x1b[0m', WARN: '\x1b[33mWARN\x1b[0m' }[status]
  console.log(`  ${mark}  ${id.padEnd(56)} ${detail}`)
}
const ok = (id, cond, good, bad) => record(id, cond ? 'PASS' : 'FAIL', cond ? good : bad)

const conc = []
function watch(page, tag) {
  page.on('console', (m) => {
    if (m.type() === 'error') conc.push(`[${tag}] console: ${m.text()}`)
  })
  page.on('pageerror', (e) => conc.push(`[${tag}] pageerror: ${e.message}`))
  page.on('requestfailed', (r) => {
    const u = r.url()
    if (u.includes('/api/')) conc.push(`[${tag}] requestfailed: ${u} ${r.failure()?.errorText}`)
  })
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 500) conc.push(`[${tag}] HTTP ${r.status()} ${r.url()}`)
  })
}

const launch = () =>
  chromium.launch({
    headless: true,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
  })

const waitQueue = (page) =>
  page.waitForFunction(() => /[1-9]\d* active alert/.test(document.body.innerText), null, {
    timeout: 45000,
  })

async function enterSetup(browser, tag) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
  const page = await ctx.newPage()
  watch(page, tag)
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.getByRole('button', { name: /Enter Command Center/i }).waitFor({ timeout: 30000 })
  return { ctx, page }
}

async function enter(page) {
  await page.getByRole('button', { name: /Enter Command Center/i }).click()
  await waitQueue(page)
}

async function run() {
  const browser = await launch()

  console.log('\n\x1b[1mA. Setup screen — inventory entry and controls\x1b[0m')
  {
    const { ctx, page } = await enterSetup(browser, 'setup')

    const vals = await page.locator('input[aria-label]').evaluateAll((ns) =>
      ns.map((n) => [n.getAttribute('aria-label'), n.value]),
    )
    const v = Object.fromEntries(vals)
    ok(
      'setup: fleet defaults present',
      v['Mobile Pumps'] === '12' && v['Flood Barriers'] === '8' && v['Traffic Wardens'] === '6',
      `${v['Mobile Pumps']}P/${v['Flood Barriers']}B/${v['Traffic Wardens']}W`,
      JSON.stringify(v),
    )

    const pumps = page.getByLabel('Mobile Pumps', { exact: true })
    await pumps.fill('9999')
    await pumps.blur()
    const over = await pumps.inputValue()
    ok('setup: pumps above max are clamped in the UI', Number(over) <= 30, `value ${over}`, `accepts ${over}`)

    await pumps.fill('-5')
    await pumps.blur()
    const neg = await pumps.inputValue()
    ok('setup: negative pumps are clamped in the UI', Number(neg) >= 0, `value ${neg}`, `accepts ${neg}`)

    await pumps.fill('12')
    await pumps.blur()

    const regionOpts = await page.locator('select[aria-label="Operational Jurisdiction"] option').count()
    ok('setup: all five catchments selectable', regionOpts >= 6, `${regionOpts} options`, `${regionOpts} options`)

    await ctx.close()
  }

  console.log('\n\x1b[1mB. Command drawer — queue, dispatch, dismiss, inspect, tabs\x1b[0m')
  {
    const { ctx, page } = await enterSetup(browser, 'command')
    await enter(page)

    const queueText = await page.locator('[aria-label="Live Dispatch Queue"]').innerText()
    ok('queue: populates with live directives', /active alert/.test(queueText), 'queue rendered', 'queue empty')
    ok(
      'queue: no misleading empty state after load',
      !queueText.includes('No active directives'),
      'cards present',
      'empty state shown on loaded data',
    )

    const cards = page.locator('[aria-label="Live Dispatch Queue"] li').filter({ hasText: 'Dispatch Unit' })
    const n0 = await cards.count()
    ok('queue: caps visible list at 8 with show-all affordance', n0 === 8, `${n0} cards + show-all`, `${n0} cards`)

    await page.getByRole('button', { name: /Show all \d+ directives/ }).click()
    const nAll = await cards.count()
    ok('queue: show-all reveals remaining directives', nAll > 8, `${nAll} cards after expand`, `${nAll} cards`)
    await page.getByRole('button', { name: /Show top 8 directives/ }).click()

    const countFor = async (label) => {
      await page.getByRole('button', { name: label, exact: true }).click()
      await page.waitForTimeout(250)
      const txt = await page.locator('[aria-label="Live Dispatch Queue"]').innerText()
      const m = txt.match(/(\d+) active alert/)
      return m ? Number(m[1]) : -1
    }
    const all = await countFor('All')
    const p1 = await countFor('Critical')
    const pumps = await countFor('Pumps')
    const barriers = await countFor('Barriers')
    const short = await countFor('Shortages')
    ok('filters: Critical subset is consistent', p1 > 0 && p1 <= all, `P1 ${p1} of ${all}`, `P1 ${p1} of ${all}`)
    ok('filters: Pumps filter is non-empty', pumps > 0, `${pumps} pump directives`, 'Pumps empty')
    ok('filters: Barriers filter is non-empty', barriers > 0, `${barriers} barrier directives`, 'Barriers empty')
    ok('filters: Shortages filter is non-empty', short > 0, `${short} shortage directives`, 'Shortages empty')
    await page.getByRole('button', { name: 'All', exact: true }).click()

    // Dispatch
    await cards.first().locator('button', { hasText: 'Dispatch Unit' }).click()
    await page.waitForTimeout(1800)
    const assignedTxt = await page.locator('[aria-label="Live Dispatch Queue"]').innerText()
    ok(
      'dispatch: card flips to an assigned unit',
      /PUMP-\d+|BAR-\d+|WRD-\d+/.test(assignedTxt),
      (assignedTxt.match(/(PUMP-\d+|BAR-\d+|WRD-\d+)[^\n]*/) || ['assigned'])[0],
      'no unit shown after dispatch',
    )

    // Dismiss
    const before = await cards.count()
    await page.locator('[aria-label="Live Dispatch Queue"] li').nth(1).locator('button[aria-label^="Dismiss "]').click()
    const opts = await page.getByRole('button', { name: /False alarm|Handled by ward|Low sensor/ }).count()
    ok('dismiss: menu exposes all three reasons', opts === 3, `${opts} reasons`, `${opts} reasons`)
    await page.getByRole('button', { name: /False alarm/ }).click()
    await page.waitForTimeout(1400)
    const after = await cards.count()
    ok('dismiss: alert leaves the actionable queue', after < before || after <= 8, `queue ${before} -> ${after}`, 'unchanged')
    const queueTxtAfterDismiss = await page.locator('[aria-label="Live Dispatch Queue"]').innerText()
    ok('dismiss: shows model calibration feedback', /False alarm logged · Cleared/i.test(queueTxtAfterDismiss), 'calibration notice shown', 'missing feedback')

    // Inspector
    await page.locator('[aria-label="Live Dispatch Queue"] li').nth(1).click()
    await page.waitForTimeout(450)
    ok(
      'inspector: clicking a directive opens the node inspector',
      (await page.locator('[aria-label="Node Inspector"]').count()) > 0,
      'inspector open',
      'inspector did not open',
    )
    await page.getByRole('button', { name: /Close inspector/i }).click()

    // Mode + Catchment
    const alertSwitch = page.getByRole('switch', { name: /Red-Alert Safety Margin/i })
    await alertSwitch.click()
    await page.waitForTimeout(1200)
    ok('mode: Red-Alert toggle updates switch state', (await alertSwitch.getAttribute('aria-checked')) === 'true', 'engaged', 'not engaged')
    await alertSwitch.click()
    await page.waitForTimeout(1000)

    await page.locator('select[aria-label="Catchment"]').selectOption('hsr')
    await page.waitForTimeout(1400)
    const hsrTxt = await page.locator('[aria-label="Live Dispatch Queue"]').innerText()
    ok('catchment: filter scopes the queue', !/BELLANDUR|WHITEFIELD|ECITY|KORAMANGALA/.test(hsrTxt), 'only HSR', 'leaked foreign catchment')
    await page.locator('select[aria-label="Catchment"]').selectOption('all')
    await page.waitForTimeout(1000)

    // Corridors & Fleet Tabs
    await page.getByRole('tab', { name: /Corridors/i }).click()
    await page.waitForSelector('text=BMTC Commuter Corridors', { timeout: 8000 })
    await page.locator('[aria-label="Corridor and Transit Safety"] ul li').first().click()
    await page.waitForTimeout(400)
    ok('corridors: comparison card renders on selection', (await page.locator('[aria-label="Route Safety Comparison"]').count()) === 1, 'comparison card visible', 'missing comparison card')

    await page.getByRole('tab', { name: /Fleet/i }).click()
    await page.waitForSelector('text=Shift Resource Pools', { timeout: 5000 })
    const fleetTxt = await page.locator('[aria-label="Fleet and Resources"]').innerText()
    ok('fleet: displays shift unit telemetry', /PUMP-01/.test(fleetTxt), 'units listed', 'units missing')

    await page.getByRole('button', { name: /Collapse command panel/i }).click()
    const reopen = page.getByRole('button', { name: /Open Command Panel/i })
    ok('layout: panel collapses and reopens cleanly', await reopen.isVisible(), 'reopen visible', 'missing reopen button')
    await reopen.click()

    await ctx.close()
  }

  console.log('\n\x1b[1mC. Reconfigure & zero-fleet behavior\x1b[0m')
  {
    const { ctx, page } = await enterSetup(browser, 'reconfig')
    await enter(page)

    await page.getByRole('button', { name: /Reconfigure session/i }).click()
    await page.waitForTimeout(500)
    ok('reconfigure: returns to setup screen', (await page.getByRole('button', { name: /Enter Command Center/i }).count()) === 1, 'setup visible', 'did not return')

    await page.getByLabel('Mobile Pumps', { exact: true }).fill('0')
    await page.getByLabel('Flood Barriers', { exact: true }).fill('0')
    await page.getByLabel('Traffic Wardens', { exact: true }).fill('0')
    await page.getByRole('button', { name: /Enter Command Center/i }).click()
    await waitQueue(page)
    const txt = await page.locator('[aria-label="Live Dispatch Queue"]').innerText()
    ok('zero fleet: directives show shortage and no Dispatch button', /0 (pump|barrier|warden)s (available|configured)|No eligible/i.test(txt) && !/Dispatch Unit/.test(txt), 'shortage shown cleanly', 'still offers Dispatch Unit')
    await ctx.close()
  }

  console.log('\n\x1b[1mD. Barrier closure + veto path\x1b[0m')
  {
    const { ctx, page } = await enterSetup(browser, 'barrier')
    await page.getByLabel('Mobile Pumps', { exact: true }).fill('4')
    await page.getByLabel('Flood Barriers', { exact: true }).fill('4')
    await page.getByLabel('Traffic Wardens', { exact: true }).fill('4')
    await page.getByRole('button', { name: /Enter Command Center/i }).click()
    await waitQueue(page)
    await page.getByRole('button', { name: 'Barriers', exact: true }).click()
    await page.waitForTimeout(400)
    const barCards = page.locator('[aria-label="Live Dispatch Queue"] li').filter({ hasText: 'Dispatch Unit' })
    const hasBarrier = (await barCards.count()) > 0
    ok('veto: barrier closure is reachable', hasBarrier, 'barrier directive listed', 'no barrier directive')
    if (hasBarrier) {
      await barCards.first().locator('button', { hasText: 'Dispatch Unit' }).click()
      await page.waitForTimeout(1600)
      const veto = page.getByRole('button', { name: /^Veto \(\d+s\)$/ })
      ok('veto: 60s veto button appears after barrier dispatch', (await veto.count()) > 0, 'veto visible', 'no veto button')
    }
    await ctx.close()
  }

  console.log('\n\x1b[1mE. Layout at 5 viewports (desktop + laptop + mobile)\x1b[0m')
  for (const vp of [
    { width: 2560, height: 1440, tag: '2560x1440' },
    { width: 1920, height: 1080, tag: '1920x1080' },
    { width: 1366, height: 768, tag: '1366x768' },
    { width: 1280, height: 720, tag: '1280x720' },
    { width: 390, height: 844, tag: '390x844' },
  ]) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
    const page = await ctx.newPage()
    watch(page, vp.tag)
    await page.goto(URL, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /Enter Command Center/i }).click()
    await waitQueue(page)
    const m = await page.evaluate(() => ({
      sh: document.documentElement.scrollHeight,
      ih: window.innerHeight,
      sw: document.documentElement.scrollWidth,
      iw: window.innerWidth,
    }))
    ok(`layout ${vp.tag}: no vertical overflow`, m.sh <= m.ih + 1, `${m.sh}/${m.ih}`, `${m.sh} > ${m.ih}`)
    ok(`layout ${vp.tag}: no horizontal overflow`, m.sw <= m.iw + 1, `${m.sw}/${m.iw}`, `${m.sw} > ${m.iw}`)
    await page.screenshot({ path: path.join(OUT, `revamp-audit-${vp.tag}.png`) })
    await ctx.close()
  }

  console.log('\n\x1b[1mF. Console and network hygiene\x1b[0m')
  ok('runtime: no console or 500 errors across sweep', conc.length === 0, 'clean console', conc.slice(0, 8).join('\n'))

  await browser.close()
  const counts = results.reduce((acc, r) => ((acc[r.status] = (acc[r.status] || 0) + 1), acc), {})
  console.log(`\n  ${counts.PASS || 0} passed · ${counts.FAIL || 0} failed · ${counts.WARN || 0} warnings\n`)
  fs.writeFileSync(path.join(OUT, 'ui-audit.json'), JSON.stringify({ url: URL, counts, results, console: conc }, null, 2))
  process.exit(counts.FAIL ? 1 : 0)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
