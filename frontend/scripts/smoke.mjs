import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createServer } from 'vite'
import { chromium } from 'playwright-core'

const server = await createServer({ server: { host: '127.0.0.1', port: 5173, strictPort: false }, logLevel: 'error' })
let browser

function mockApi(page) {
  const calls = { lastAsk: null }
  const documents = [{
    id: 'memo-1', filename: 'policy.pdf', title: 'Graduate Policy Memo',
    source_url: 'https://example.edu/policy.pdf', institution: 'UC Berkeley',
    published_or_updated_date: '2018-09-25', extraction_warnings: [], chunk_count: 2,
  }]

  return page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    if (path === '/documents' && request.method() === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(documents) })
    }
    if (path === '/documents' && request.method() === 'POST') {
      const document = {
        id: 'memo-2', filename: 'new-policy.txt', title: 'New Policy', source_url: null,
        institution: null, published_or_updated_date: null, extraction_warnings: [], chunk_count: 1,
      }
      documents.unshift(document)
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(document) })
    }
    if (path.startsWith('/documents/') && request.method() === 'DELETE') {
      const id = decodeURIComponent(path.slice('/documents/'.length))
      const index = documents.findIndex((document) => document.id === id)
      if (index >= 0) documents.splice(index, 1)
      return route.fulfill({ status: 204, body: '' })
    }
    if (path === '/ask' && request.method() === 'POST') {
      const payload = request.postDataJSON()
      calls.lastAsk = payload
      const question = payload.question
      await new Promise((resolve) => setTimeout(resolve, 120))
      if (question.toLowerCase().includes('simulate error')) {
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Model service unavailable.' }) })
      }
      const response = question.toLowerCase().includes('parking')
        ? { answer: 'I could not find that in the uploaded documents.', citations: [] }
        : { answer: 'The September 2018 memo required one summer unit [1].', citations: [{
          number: 1, document_id: 'memo-1', title: 'Graduate Policy Memo',
          source_url: 'https://example.edu/policy.pdf', institution: 'UC Berkeley',
          published_or_updated_date: '2018-09-25', page: 2,
          excerpt: 'As of 2019, students will be required to enroll in one unit in Summer Sessions.',
        }] }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
    }
    return route.fulfill({ status: 404, body: 'Not found' })
  }).then(() => calls)
}

try {
  await server.listen()
  const address = server.httpServer.address()
  const origin = `http://127.0.0.1:${address.port}`
  browser = await chromium.launch(process.env.CAMPUSLENS_BROWSER
    ? { executablePath: process.env.CAMPUSLENS_BROWSER, headless: true }
    : { channel: 'msedge', headless: true })
  await mkdir('.screenshots', { recursive: true })

  const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const desktopApi = await mockApi(desktop)
  await desktop.goto(origin)
  await desktop.getByRole('heading', { name: 'Ask a question' }).waitFor()
  await desktop.getByText('Graduate Policy Memo').first().waitFor()
  await desktop.keyboard.press('Tab')
  assert.equal(await desktop.evaluate(() => document.activeElement?.className), 'skip-link')
  await desktop.keyboard.press('Enter')
  assert.equal(await desktop.evaluate(() => document.activeElement?.id), 'main-content')
  const questionBox = desktop.getByLabel('Your question')
  await questionBox.fill('What did the memo require?')
  await questionBox.focus()
  await desktop.keyboard.press('Tab')
  assert.match(await desktop.evaluate(() => document.activeElement?.textContent || ''), /Ask CampusLens/)
  await desktop.keyboard.press('Enter')
  await desktop.getByText('Reading the relevant passages and checking citations…').waitFor()
  await desktop.getByRole('heading', { name: 'Answer with sources' }).waitFor()
  await desktop.getByRole('link', { name: 'View source 1' }).click()
  assert.match(desktop.url(), /#citation-1$/)
  assert.match(await desktop.getByRole('link', { name: /Open source PDF/ }).getAttribute('href'), /#page=2$/)
  await desktop.screenshot({ path: '.screenshots/desktop.png', fullPage: true })

  await desktop.getByRole('checkbox', { name: 'Use only selected documents: Graduate Policy Memo' }).check()
  await desktop.getByRole('button', { name: /Ask CampusLens/ }).click()
  await desktop.getByRole('heading', { name: 'Answer with sources' }).waitFor()
  assert.deepEqual(desktopApi.lastAsk.document_ids, ['memo-1'])
  await desktop.getByRole('checkbox', { name: 'Use only selected documents: Graduate Policy Memo' }).uncheck()

  await questionBox.fill('What is the current parking permit price?')
  await desktop.getByRole('button', { name: /Ask CampusLens/ }).click()
  await desktop.getByRole('heading', { name: 'No supported answer found' }).waitFor()
  assert.equal(await desktop.locator('.citation-card').count(), 0)

  await questionBox.fill('Simulate error from backend')
  await desktop.getByRole('button', { name: /Ask CampusLens/ }).click()
  await desktop.getByRole('alert').getByText('Model service unavailable.').waitFor()

  await desktop.getByRole('button', { name: '+ Add' }).click()
  await desktop.locator('#document-file').setInputFiles({ name: 'new-policy.txt', mimeType: 'text/plain', buffer: Buffer.from('New policy text') })
  await desktop.locator('#document-title').fill('New Policy')
  await desktop.getByRole('button', { name: 'Upload and index' }).click()
  await desktop.getByText('Added New Policy. It is ready for questions.').waitFor()
  desktop.once('dialog', (dialog) => dialog.accept())
  await desktop.getByRole('button', { name: 'Delete New Policy' }).click()
  await desktop.getByText('Deleted New Policy.').waitFor()
  desktop.once('dialog', (dialog) => dialog.accept())
  await desktop.getByRole('button', { name: 'Delete Graduate Policy Memo' }).click()
  await desktop.getByText('No documents yet.').waitFor()
  assert.equal(await desktop.getByRole('button', { name: /Ask CampusLens/ }).isDisabled(), true)
  assert.equal(await desktop.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await mockApi(mobile)
  await mobile.goto(origin)
  await mobile.getByRole('heading', { name: 'Ask a question' }).waitFor()
  await mobile.getByLabel('Your question').fill('What did the memo require?')
  await mobile.getByRole('button', { name: /Ask CampusLens/ }).click()
  await mobile.getByRole('heading', { name: 'Answer with sources' }).waitFor()
  assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  await mobile.screenshot({ path: '.screenshots/mobile.png', fullPage: true })
  console.log('Desktop, mobile, keyboard, citations, filters, refusal, loading, error, empty, upload, and delete smoke checks passed.')
} finally {
  await browser?.close()
  await server.close()
}
