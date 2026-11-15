import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const URL = process.env.VERIFY_URL || 'http://127.0.0.1:8000/'
const OUT_DIR = path.resolve('..', 'scratch', 'verification')
fs.mkdirSync(OUT_DIR, { recursive: true })

async function run() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'],
  })
  const errors = []

  try {
    for (const vp of [
      { width: 1920, height: 1080, tag: 'desktop-1920' },
      { width: 1366, height: 768, tag: 'laptop-1366' },
      { width: 390, height: 844, tag: 'mobile-390' },
    ]) {
      const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
      const page = await context.newPage()
      page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(`[${vp.tag}] console.error: ${msg.text()}`)
      })
      page.on('pageerror', (err) => {
        errors.push(`[${vp.tag}] pageerror: ${err.message}`)
      })

      await page.goto(URL, { waitUntil: 'networkidle', timeout: 25000 })

      // Step 1: Verify SetupScreen renders and submit initial municipal fleet
      const setupBtn = page.getByRole('button', { name: /Enter Command Center/i })
      await setupBtn.waitFor({ timeout: 10000 })
      const pumpsInput = page.getByLabel('Mobile Pumps', { exact: true })
      await pumpsInput.fill('12')
      await page.screenshot({ path: path.join(OUT_DIR, `revamp-${vp.tag}-setup.png`) })
      await setupBtn.click()

      // Step 2: Wait for live full-bleed map & floating HUD
      await page.waitForSelector('text=Priority Directives', { timeout: 15000 })
      await page.waitForFunction(() => /\d+ active alert/.test(document.body.innerText), null, {
        timeout: 15000,
      })
      await page.waitForTimeout(900)

      const metrics = await page.evaluate(() => {
        const doc = document.documentElement
        const bodyText = document.body.innerText
        return {
          scrollHeight: doc.scrollHeight,
          innerHeight: window.innerHeight,
          scrollWidth: doc.scrollWidth,
          innerWidth: window.innerWidth,
          hasForbiddenDebugText:
            /\bFPS\b|\bSUPPRESSED\b|SITUATION LOG|Duty Officer|T\+\d{3}m/.test(bodyText),
          canvases: document.querySelectorAll('canvas').length,
          queueItems: document.querySelectorAll('[aria-label="Live Dispatch Queue"] li').length,
        }
      })

      console.log(`[${vp.tag}] metrics:`, JSON.stringify(metrics))
      if (metrics.scrollHeight !== metrics.innerHeight) {
        throw new Error(
          `[${vp.tag}] vertical scroll mismatch: scrollHeight=${metrics.scrollHeight} innerHeight=${metrics.innerHeight}`,
        )
      }
      if (metrics.scrollWidth !== metrics.innerWidth) {
        throw new Error(
          `[${vp.tag}] horizontal scroll mismatch: scrollWidth=${metrics.scrollWidth} innerWidth=${metrics.innerWidth}`,
        )
      }
      if (metrics.hasForbiddenDebugText) {
        throw new Error(`[${vp.tag}] forbidden debug telemetry text present in UI`)
      }
      if (metrics.canvases < 1 || metrics.queueItems < 1) {
        throw new Error(`[${vp.tag}] missing required UI elements: ${JSON.stringify(metrics)}`)
      }

      // Test Dispatch Unit on first directive
      const dispatchBtn = page.getByRole('button', { name: /Dispatch Unit/i }).first()
      await dispatchBtn.waitFor({ timeout: 8000 })
      await dispatchBtn.click()
      await page.waitForTimeout(800)
      await page.screenshot({ path: path.join(OUT_DIR, `revamp-${vp.tag}-dispatch.png`) })

      // Open Node Inspector by clicking second card
      if (vp.tag === 'desktop-1920') {
        await page.locator('[aria-label="Live Dispatch Queue"] li').nth(1).click()
        await page.waitForSelector('[aria-label="Node Inspector"]', { timeout: 5000 })
        await page.waitForTimeout(1450)
        await page.screenshot({ path: path.join(OUT_DIR, `revamp-${vp.tag}-inspector.png`) })
        await page.getByRole('button', { name: /Close inspector/i }).click()
      }

      // Switch to Tab 2: Corridors & Transit Safety
      await page.getByRole('tab', { name: /Corridors/i }).click()
      await page.waitForSelector('text=BMTC Commuter Corridors', { timeout: 8000 })
      await page.locator('[aria-label="Corridor and Transit Safety"] ul li').first().click()
      await page.waitForTimeout(1450)
      if (vp.tag === 'desktop-1920') {
        await page.getByRole('switch', { name: /Bus Routes/i }).click()
        await page.getByRole('switch', { name: /Hospitals/i }).click()
        await page.waitForTimeout(300)
      }
      await page.screenshot({ path: path.join(OUT_DIR, `revamp-${vp.tag}-corridors.png`) })

      // Test 2-point map click Corridor Picker on desktop
      if (vp.tag === 'desktop-1920') {
        await page.getByRole('button', { name: /Pick A → B on Map/i }).click()
        await page.waitForSelector('text=set Origin A', { timeout: 3000 })
        const mainBox = await page.locator('main').boundingBox()
        if (!mainBox) throw new Error(`[${vp.tag}] missing main map boundingBox`)
        await page.mouse.click(mainBox.x + mainBox.width * 0.34, mainBox.y + mainBox.height * 0.48)
        await page.waitForSelector('text=Destination B', { timeout: 5000 })
        await page.mouse.click(mainBox.x + mainBox.width * 0.48, mainBox.y + mainBox.height * 0.50)
        await page.waitForSelector('[aria-label="Route Safety Comparison"]', { timeout: 8000 })
        await page.waitForSelector('[aria-label="Clear active route"]', { timeout: 8000 })
      }

      // Switch to Tab 3: Fleet & Resources
      await page.getByRole('tab', { name: /Fleet/i }).click()
      await page.waitForSelector('text=Shift Resource Pools', { timeout: 5000 })
      await page.waitForTimeout(350)
      if (vp.tag === 'desktop-1920') {
        await page.screenshot({ path: path.join(OUT_DIR, `revamp-${vp.tag}-fleet.png`) })
      }

      // Test Collapsing & Re-opening Command Panel
      await page.getByRole('button', { name: /Collapse command panel/i }).click()
      const reopenBtn = page.getByRole('button', { name: /Open Command Panel/i })
      await reopenBtn.waitFor({ timeout: 5000 })
      await reopenBtn.click()
      await page.waitForSelector('text=Shift Resource Pools', { timeout: 5000 })

      const postToggleZeroScroll = await page.evaluate(
        () => document.documentElement.scrollHeight === window.innerHeight,
      )
      if (!postToggleZeroScroll) {
        throw new Error(`[${vp.tag}] scrollHeight != innerHeight after panel toggle`)
      }

      await context.close()
    }

    if (errors.length > 0) {
      throw new Error(`Console/page errors observed:\n${errors.join('\n')}`)
    }
    console.log('ALL PLAYWRIGHT VERIFICATION GATES PASSED')
  } finally {
    await browser.close()
  }
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
