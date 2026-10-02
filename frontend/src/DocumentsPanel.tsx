import { useRef, useState, type FormEvent } from 'react'
import { deleteDocument, uploadDocument, type DocumentRecord } from './api'

const MAX_FILE_BYTES = 10 * 1024 * 1024

interface Props {
  documents: DocumentRecord[]
  loading: boolean
  selectedIds: Set<string>
  onToggle: (id: string) => void
  onUploaded: (document: DocumentRecord) => void
  onDeleted: (id: string) => void
  onError: (message: string) => void
  onNotice: (message: string) => void
}

export default function DocumentsPanel({ documents, loading, selectedIds, onToggle, onUploaded, onDeleted, onError, onNotice }: Props) {
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const formRef = useRef<HTMLFormElement>(null)

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const file = data.get('file')
    if (!(file instanceof File) || !file.name) return onError('Choose a PDF or text file first.')
    if (file.size > MAX_FILE_BYTES) return onError('Files must be 10 MB or smaller.')
    for (const field of ['title', 'source_url', 'institution', 'published_or_updated_date']) {
      if (!String(data.get(field) || '').trim()) data.delete(field)
    }
    setUploading(true)
    onError('')
    try {
      const document = await uploadDocument(data)
      onUploaded(document)
      formRef.current?.reset()
      setUploadOpen(false)
      onNotice(`Added ${document.title}. It is ready for questions.`)
    } catch (error) {
      onError(error instanceof Error ? error.message : 'The upload failed.')
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(document: DocumentRecord) {
    if (!window.confirm(`Delete “${document.title}” and its search index?`)) return
    setDeletingId(document.id)
    onError('')
    try {
      await deleteDocument(document.id)
      onDeleted(document.id)
      onNotice(`Deleted ${document.title}.`)
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Could not delete the document.')
    } finally {
      setDeletingId(null)
    }
  }

  return <aside className="documents-panel" aria-labelledby="documents-title">
    <div className="panel-head">
      <div>
        <p className="eyebrow">Your library</p>
        <h2 id="documents-title">Documents <span className="count-pill">{documents.length}</span></h2>
      </div>
      <button type="button" className="add-button" onClick={() => setUploadOpen(!uploadOpen)} aria-expanded={uploadOpen} aria-controls="upload-form">
        {uploadOpen ? 'Close' : '+ Add'}
      </button>
    </div>

    {uploadOpen && <form id="upload-form" className="upload-form" ref={formRef} onSubmit={handleUpload}>
      <label htmlFor="document-file">Document <span aria-hidden="true">*</span></label>
      <input id="document-file" name="file" type="file" accept=".pdf,.txt,application/pdf,text/plain" required />
      <p className="field-hint">PDF or UTF-8 text, up to 10 MB.</p>
      <label htmlFor="document-title">Title <span className="optional">optional</span></label>
      <input id="document-title" name="title" type="text" placeholder="e.g. Graduate policy memo" />
      <label htmlFor="document-url">Original source URL <span className="optional">optional</span></label>
      <input id="document-url" name="source_url" type="url" placeholder="https://university.edu/policy.pdf" />
      <label htmlFor="document-institution">Institution <span className="optional">optional</span></label>
      <input id="document-institution" name="institution" type="text" placeholder="e.g. UC Berkeley" />
      <label htmlFor="document-date">Published or updated <span className="optional">optional</span></label>
      <input id="document-date" name="published_or_updated_date" type="date" />
      <button type="submit" className="primary-button upload-submit" disabled={uploading}>{uploading ? 'Indexing document…' : 'Upload and index'}</button>
    </form>}

    <div className="document-list-intro">
      <p>{selectedIds.size ? `Questions limited to ${selectedIds.size} selected ${selectedIds.size === 1 ? 'document' : 'documents'}.` : 'Select documents to narrow an answer, or use the full library.'}</p>
      {selectedIds.size > 0 && <button type="button" className="text-button" onClick={() => documents.forEach((document) => selectedIds.has(document.id) && onToggle(document.id))}>Clear selection</button>}
    </div>

    {loading ? <p className="document-state" role="status">Loading documents…</p> : documents.length === 0
      ? <div className="document-empty"><span aria-hidden="true">▤</span><p>No documents yet.</p><small>Add a PDF or text file to start asking questions.</small></div>
      : <ul className="document-list">{documents.map((document) => <li key={document.id} className="document-item">
        <label className="document-select">
          <input type="checkbox" checked={selectedIds.has(document.id)} onChange={() => onToggle(document.id)} aria-label={`Use only selected documents: ${document.title}`} />
          <span className="document-icon" aria-hidden="true">{document.filename.toLowerCase().endsWith('.pdf') ? 'PDF' : 'TXT'}</span>
          <span className="document-info"><strong>{document.title}</strong><small>{document.institution || 'Uploaded document'} · {document.chunk_count} {document.chunk_count === 1 ? 'chunk' : 'chunks'}</small></span>
        </label>
        <div className="document-actions">
          {document.source_url?.startsWith('https://') || document.source_url?.startsWith('http://')
            ? <a href={document.source_url} target="_blank" rel="noopener noreferrer">Source ↗</a> : null}
          <button type="button" onClick={() => handleDelete(document)} disabled={deletingId === document.id} aria-label={`Delete ${document.title}`}>
            {deletingId === document.id ? 'Deleting…' : 'Delete'}
          </button>
        </div>
        {document.extraction_warnings.length > 0 && <p className="extraction-warning">Some PDF pages had no extractable text.</p>}
      </li>)}</ul>}
  </aside>
}
