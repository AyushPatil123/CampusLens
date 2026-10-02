import { useEffect, useRef, useState, type FormEvent } from 'react'
import AnswerView from './AnswerView'
import DocumentsPanel from './DocumentsPanel'
import { askQuestion, listDocuments, type AskResponse, type DocumentRecord } from './api'

const examples = [
  'What was the 2018 Graduate Division fellowship stipend cap?',
  'How did summer filing enrollment change between the 2015 and 2018 memos?',
  'What is the current campus parking permit price?',
]

export default function App() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [documentsLoading, setDocumentsLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [question, setQuestion] = useState('')
  const [askedQuestion, setAskedQuestion] = useState('')
  const [result, setResult] = useState<AskResponse | null>(null)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const questionRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    let active = true
    listDocuments()
      .then((records) => { if (active) setDocuments(records) })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : 'Could not load documents.') })
      .finally(() => { if (active) setDocumentsLoading(false) })
    return () => { active = false }
  }, [])

  function toggleDocument(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = question.trim()
    if (trimmed.length < 3) return setError('Enter a question with at least three characters.')
    setAsking(true)
    setError('')
    setNotice('')
    setResult(null)
    try {
      const response = await askQuestion(trimmed, [...selectedIds])
      setAskedQuestion(trimmed)
      setResult(response)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not get an answer.')
    } finally {
      setAsking(false)
    }
  }

  function useExample(example: string) {
    setQuestion(example)
    questionRef.current?.focus()
  }

  function removeDocument(id: string) {
    setDocuments((current) => current.filter((document) => document.id !== id))
    setSelectedIds((current) => { const next = new Set(current); next.delete(id); return next })
    setResult(null)
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to question</a>
    <header className="site-header">
      <div className="brand"><span className="brand-mark" aria-hidden="true"><span /></span><span>Campus<span>Lens</span></span></div>
      <div className="header-right"><span className="scope-pill">Document-backed answers</span><span className="header-note">Local research workspace</span></div>
    </header>

    <div className="hero-band">
      <div className="hero-copy">
        <p className="eyebrow">Ask the document. Check the evidence.</p>
        <h1>Clear answers,<br /><em>visible sources.</em></h1>
        <p>Search university documents and trace every answer back to the exact page and excerpt that supports it.</p>
      </div>
      <div className="hero-decor" aria-hidden="true"><div className="decor-page decor-page-back" /><div className="decor-page decor-page-front"><span /><span /><span /><i>[1]</i></div></div>
    </div>

    <div className="workspace">
      <DocumentsPanel
        documents={documents} loading={documentsLoading} selectedIds={selectedIds}
        onToggle={toggleDocument} onUploaded={(document) => setDocuments((current) => [document, ...current])}
        onDeleted={removeDocument} onError={(message) => { setError(message); if (message) setNotice('') }}
        onNotice={(message) => { setNotice(message); setError('') }}
      />

      <main id="main-content" className="main-panel" tabIndex={-1}>
        <div className="section-heading">
          <div><p className="eyebrow">Explore your sources</p><h2>Ask a question</h2></div>
          <span className="step-label">01 / ASK</span>
        </div>
        <p className="section-description">Ask about a policy, a date, or a change between documents. Answers use only your uploaded sources.</p>
        <form className="question-form" onSubmit={handleAsk}>
          <label htmlFor="question">Your question</label>
          <textarea id="question" ref={questionRef} value={question} onChange={(event) => setQuestion(event.target.value)}
            placeholder="What did the 2018 memo say about summer enrollment?" minLength={3} maxLength={1000} rows={4} required />
          <div className="composer-footer"><span>{question.length}/1000 characters</span><button className="primary-button" type="submit" disabled={asking || documentsLoading || documents.length === 0}>
            {asking ? 'Checking sources…' : 'Ask CampusLens'} <span aria-hidden="true">→</span>
          </button></div>
        </form>
        <div className="examples"><span>Try a question</span><div>{examples.map((example) => <button type="button" key={example} onClick={() => useExample(example)}>{example} <span aria-hidden="true">↗</span></button>)}</div></div>

        {error && <div className="message error-message" role="alert">{error}</div>}
        {notice && <div className="message notice-message" role="status">{notice}</div>}
        {asking && <div className="answer-placeholder" role="status" aria-live="polite"><span className="loading-dot" /> Reading the relevant passages and checking citations…</div>}
        {!asking && result && <AnswerView result={result} question={askedQuestion} />}
        {!asking && !result && <div className="answer-placeholder idle-placeholder"><span className="placeholder-icon" aria-hidden="true">↳</span><div><strong>Your answer will appear here</strong><p>Each numbered citation opens its source excerpt below the answer.</p></div></div>}
      </main>
    </div>

    <footer className="site-footer"><span>CampusLens · A citation-backed university document assistant</span><span>Historical documents may have been superseded. Check the current university policy before acting.</span></footer>
  </div>
}
