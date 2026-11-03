/**
 * The remove control, which is the first destructive thing this UI has ever
 * drawn. Two claims matter and neither is visible from reading the component:
 * it appears only where the *server* said the document is the caller's, and it
 * asks before it goes.
 *
 * The id's prefix is not the test, and must not become one: behind the gate the
 * owner is the name the proxy vouched for rather than this browser's client id,
 * so a UI that decided for itself would be wrong for exactly the deployment
 * with more than one person in it.
 */
import { render, screen, waitFor } from '@testing-library/react'
import { useRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CorpusCard } from './corpus-card'
import type { CorpusState } from './corpus-card'
import type { DocumentListing } from '@/lib/types'

const listing: DocumentListing = {
  count: 2,
  documents: [
    { id: 'upload:ada:notes', title: 'My notes', chunks: 3, yours: true },
    { id: 'handbook', title: 'The shared handbook', chunks: 9, yours: false },
  ],
}

const { fetchDocuments, forgetDocument, uploadFiles } = vi.hoisted(() => ({
  fetchDocuments: vi.fn(),
  forgetDocument: vi.fn(),
  uploadFiles: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ fetchDocuments, forgetDocument, uploadFiles }))

const corpus: CorpusState = {
  status: 'ready',
  stats: {
    documents: 2,
    collection_size: 12,
    embedding_model: 'all-MiniLM-L6-v2',
    reranker: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  },
}

function Harness() {
  const pickRef = useRef<(() => void) | null>(null)
  return <CorpusCard corpus={corpus} supported={['.pdf']} onRefresh={() => {}} pickRef={pickRef} />
}

const show = async () => {
  render(<Harness />)
  await waitFor(() => expect(screen.getByText('My notes')).toBeTruthy())
}

beforeEach(() => {
  vi.clearAllMocks()
  fetchDocuments.mockResolvedValue(listing)
  forgetDocument.mockResolvedValue({
    success: true,
    message: 'Removed upload:ada:notes and its 3 chunk(s)',
    chunks_removed: 3,
    collection_size: 9,
  })
})

describe('whose documents carry a remove control', () => {
  it('draws one for a document the server called yours', async () => {
    await show()
    expect(screen.getByLabelText('Remove My notes')).toBeTruthy()
  })

  it('draws none for a document it did not', async () => {
    await show()
    expect(screen.getByText('The shared handbook')).toBeTruthy()
    expect(screen.queryByLabelText('Remove The shared handbook')).toBeNull()
  })
})

describe('what one click does', () => {
  it('asks, and removes nothing yet', async () => {
    await show()
    screen.getByLabelText('Remove My notes').click()
    await waitFor(() => expect(screen.getByText('Remove')).toBeTruthy())
    expect(forgetDocument).not.toHaveBeenCalled()
  })

  it('removes the document only on the second', async () => {
    await show()
    screen.getByLabelText('Remove My notes').click()
    await waitFor(() => expect(screen.getByText('Remove')).toBeTruthy())
    screen.getByText('Remove').click()
    await waitFor(() => expect(forgetDocument).toHaveBeenCalledWith('upload:ada:notes'))
  })

  it('leaves it alone when the question is declined', async () => {
    await show()
    screen.getByLabelText('Remove My notes').click()
    await waitFor(() => expect(screen.getByText('Cancel')).toBeTruthy())
    screen.getByText('Cancel').click()
    await waitFor(() => expect(screen.getByLabelText('Remove My notes')).toBeTruthy())
    expect(forgetDocument).not.toHaveBeenCalled()
  })
})

describe('what the listing does when it cannot be had', () => {
  it('shows the upload box and no rows rather than failing', async () => {
    fetchDocuments.mockResolvedValue(null)
    render(<Harness />)
    await waitFor(() => expect(fetchDocuments).toHaveBeenCalled())
    expect(screen.getByText(/Drop files/)).toBeTruthy()
    expect(screen.queryByText('My notes')).toBeNull()
  })
})
