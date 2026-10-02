import { useState, type ReactNode } from 'react'
import type { AskResponse, Citation } from './api'

function sourcePageUrl(sourceUrl: string | null, page: number): string | null {
  if (!sourceUrl) return null
  try {
    const url = new URL(sourceUrl)
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null
    url.hash = `page=${page}`
    return url.toString()
  } catch {
    return null
  }
}

function inlineContent(text: string, citations: Citation[]): ReactNode[] {
  const citationNumbers = new Set(citations.map((citation) => citation.number))
  return text.split(/(\[\d+\]|\*\*[^*]+\*\*)/g).map((part, index) => {
    const match = part.match(/^\[(\d+)\]$/)
    if (match) {
      const number = Number(match[1])
      return citationNumbers.has(number)
        ? <a className="citation-marker" href={`#citation-${number}`} key={index} aria-label={`View source ${number}`}>[{number}]</a>
        : <span key={index}>{part}</span>
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

function AnswerText({ answer, citations }: AskResponse) {
  const blocks = answer.trim().split(/\n\s*\n/)
  return <div className="answer-copy">
    {blocks.map((block, index) => {
      const lines = block.split('\n').map((line) => line.trim()).filter(Boolean)
      if (lines.length === 1 && /^#{1,3}\s/.test(lines[0])) {
        return <h3 key={index}>{inlineContent(lines[0].replace(/^#{1,3}\s/, ''), citations)}</h3>
      }
      if (lines.every((line) => /^[-*]\s/.test(line))) {
        return <ul key={index}>{lines.map((line, item) => <li key={item}>{inlineContent(line.slice(2), citations)}</li>)}</ul>
      }
      if (lines.every((line) => /^\d+\.\s/.test(line))) {
        return <ol key={index}>{lines.map((line, item) => <li key={item}>{inlineContent(line.replace(/^\d+\.\s/, ''), citations)}</li>)}</ol>
      }
      return <p key={index}>{lines.map((line, item) => <span key={item}>{item > 0 && <br />}{inlineContent(line, citations)}</span>)}</p>
    })}
  </div>
}

function CitationCard({ citation }: { citation: Citation }) {
  const [expanded, setExpanded] = useState(false)
  const text = citation.excerpt.trim()
  const clipped = text.length > 430
  const pageUrl = sourcePageUrl(citation.source_url, citation.page)

  return <article className="citation-card" id={`citation-${citation.number}`} tabIndex={-1}>
    <div className="citation-head">
      <span className="citation-index" aria-hidden="true">{citation.number}</span>
      <div>
        <h4>{citation.title}</h4>
        <p>Page {citation.page}{citation.published_or_updated_date ? ` · ${citation.published_or_updated_date}` : ''}</p>
      </div>
    </div>
    <blockquote>{expanded || !clipped ? text : `${text.slice(0, 430).trimEnd()}…`}</blockquote>
    <div className="citation-actions">
      {clipped && <button type="button" className="text-button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        {expanded ? 'Show less' : 'Read full excerpt'}
      </button>}
      {pageUrl && <a href={pageUrl} target="_blank" rel="noopener noreferrer" className="source-link">
        Open source PDF <span aria-hidden="true">↗</span>
      </a>}
    </div>
  </article>
}

export default function AnswerView({ result, question }: { result: AskResponse, question: string }) {
  const hasCitations = result.citations.length > 0
  return <section className="answer-result" aria-labelledby="answer-title">
    <div className="section-heading">
      <div>
        <p className="eyebrow">Response</p>
        <h2 id="answer-title">{hasCitations ? 'Answer with sources' : 'No supported answer found'}</h2>
      </div>
      <span className={`result-badge ${hasCitations ? 'is-sourced' : 'is-unsourced'}`}>
        {hasCitations ? `${result.citations.length} cited ${result.citations.length === 1 ? 'excerpt' : 'excerpts'}` : 'No citations'}
      </span>
    </div>
    <p className="asked-question">“{question}”</p>
    {!hasCitations && <p className="refusal-note">The uploaded documents did not provide enough evidence for this answer. This does not mean the university has no policy on the topic.</p>}
    <AnswerText {...result} />
    {hasCitations && <div className="sources-section" aria-label="Cited source excerpts">
      <div className="sources-heading"><h3>Check the sources</h3><p>Select a number in the answer to jump here.</p></div>
      <div className="citation-grid">{result.citations.map((citation) => <CitationCard key={citation.number} citation={citation} />)}</div>
    </div>}
  </section>
}
