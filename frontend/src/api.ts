export interface DocumentRecord {
  id: string
  filename: string
  title: string
  source_url: string | null
  institution: string | null
  published_or_updated_date: string | null
  extraction_warnings: string[]
  chunk_count: number
}

export interface Citation {
  number: number
  document_id: string
  title: string
  source_url: string | null
  institution: string | null
  published_or_updated_date: string | null
  page: number
  excerpt: string
}

export interface AskResponse {
  answer: string
  citations: Citation[]
}

const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => typeof item?.msg === 'string' ? item.msg : null)
      .filter(Boolean)
    if (messages.length) return messages.join('. ')
  }
  if (status === 429) return 'The model is busy or out of quota. Try again later.'
  return `Request failed (${status}). Please try again.`
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, options)
  } catch {
    throw new Error('Could not reach the backend. Start the FastAPI server and try again.')
  }

  if (!response.ok) {
    let detail: unknown
    try {
      detail = (await response.json()).detail
    } catch {
      detail = undefined
    }
    throw new Error(errorMessage(detail, response.status))
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function listDocuments(): Promise<DocumentRecord[]> {
  return request('/documents')
}

export function askQuestion(question: string, documentIds: string[]): Promise<AskResponse> {
  return request('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, ...(documentIds.length ? { document_ids: documentIds } : {}) }),
  })
}

export function uploadDocument(data: FormData): Promise<DocumentRecord> {
  return request('/documents', { method: 'POST', body: data })
}

export function deleteDocument(id: string): Promise<void> {
  return request(`/documents/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
