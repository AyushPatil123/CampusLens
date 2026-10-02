// Reproducible UI illustrations, using fictional source text and API fixtures.
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createServer } from 'vite'
import { chromium } from 'playwright-core'

const output = new URL('../../docs/screenshots/', import.meta.url)
const server = await createServer({ server: { host: '127.0.0.1', port: 5173, strictPort: false }, logLevel: 'error' })
let browser
const excerpt = 'Students must submit the demonstration fellowship application by October 15. Applications require a research summary and one faculty recommendation.'
try {
  await mkdir(output, { recursive: true })
  await server.listen()
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`
  browser = await chromium.launch(process.env.CAMPUSLENS_BROWSER
    ? { executablePath: process.env.CAMPUSLENS_BROWSER, headless: true }
    : { channel: 'msedge', headless: true })
  for (const [name, width, height] of [['desktop', 1440, 1100], ['mobile', 390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 })
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      const document = { id: 'illustration', filename: 'demo-fellowship.pdf', title: 'Demo fellowship policy (fictional)',
        source_url: `${origin}/illustration-source`, institution: 'Example University (fictional)',
        published_or_updated_date: '2026-10-01', extraction_warnings: [], chunk_count: 1 }
      const response = path.endsWith('/documents') ? [document]
        : { answer: 'Submit the demonstration fellowship application by **October 15**, with a research summary and one faculty recommendation [1].',
          citations: [{ ...document, document_id: document.id, number: 1, page: 1, excerpt }] }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
    })
    await page.context().route('**/illustration-source*', (route) => route.fulfill({ contentType: 'text/html', body:
      `<html><head><meta charset="utf-8"><title>Fictional source — page 1</title></head><body style="font-family:Georgia,serif;background:#eceeea;padding:48px;color:#182a25"><main style="background:white;max-width:740px;margin:auto;padding:64px;min-height:700px"><p>EXAMPLE UNIVERSITY · FICTIONAL DEMONSTRATION DOCUMENT</p><h1>Demo fellowship policy</h1><p>Page 1 · October 1, 2026</p><hr><h2>Application requirements</h2><p style="font-size:22px;line-height:1.7">${excerpt}</p><p>This original fixture illustrates source verification. It is not a university policy or a model evaluation result.</p></main></body></html>` }))
    await page.goto(origin)
    await page.getByText('Demo fellowship policy (fictional)').first().waitFor()
    await page.getByLabel('Your question').fill('When is the demo fellowship application due, and what should I include?')
    await page.getByRole('button', { name: /Ask CampusLens/ }).click()
    await page.getByRole('heading', { name: 'Answer with sources' }).waitFor()
    await page.getByRole('link', { name: 'View source 1' }).click()
    assert.equal(await page.locator('.citation-card').count(), 1)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await page.evaluate(() => scrollTo(0, 0))
    await page.screenshot({ path: new URL(`${name}.png`, output).pathname.replace(/^\/(\w:)/, '$1'), fullPage: true })
    if (name === 'desktop') {
      const opened = page.waitForEvent('popup')
      await page.getByRole('link', { name: /Open source PDF/ }).click()
      const source = await opened
      await source.waitForLoadState()
      await source.getByRole('heading', { name: 'Demo fellowship policy', exact: true }).waitFor()
      assert.match(source.url(), /#page=1$/)
      await source.screenshot({ path: new URL('source-page.png', output).pathname.replace(/^\/(\w:)/, '$1'), fullPage: true })
      await source.close()
    }
    await page.close()
  }
  console.log('Saved desktop, mobile, and fictional source-page illustrations in docs/screenshots/. No model calls.')
} finally {
  await browser?.close()
  await server.close()
}
