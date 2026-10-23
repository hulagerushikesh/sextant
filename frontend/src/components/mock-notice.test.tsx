/**
 * The only warning in the app, and the one element that was hidden on a
 * phone. These pin both halves: that it appears at all, and that nothing
 * about its styling can take it away again at a breakpoint.
 */
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const load = async (mock: '0' | '1') => {
  vi.stubEnv('VITE_MOCK', mock)
  vi.resetModules()
  const [{ MockNotice }, { MOCK_NOTICE }] = await Promise.all([
    import('./mock-notice'),
    import('@/lib/api'),
  ])
  return { MockNotice, MOCK_NOTICE }
}

afterEach(() => vi.unstubAllEnvs())

describe('the warning that hides on a phone', () => {
  it('renders nothing at all when the data is real', async () => {
    const { MockNotice } = await load('0')
    const { container } = render(<MockNotice />)
    expect(container.innerHTML).toBe('')
  })

  it('shows when the data is invented', async () => {
    const { MockNotice } = await load('1')
    render(<MockNotice />)
    expect(screen.getByRole('status')).toBeTruthy()
  })

  it('is not hidden at any breakpoint', async () => {
    // The whole defect: `hidden ... sm:inline-flex` meant the one mark saying
    // every figure on screen is invented was absent below 640px -- the screen
    // with the least room to notice from context.
    const { MockNotice } = await load('1')
    render(<MockNotice />)
    const classes = screen.getByRole('status').className.split(/\s+/)
    expect(classes).not.toContain('hidden')
    expect(classes.some((c) => /^(sm|md|lg|xl|2xl):(inline|block|flex|inline-flex)/.test(c))).toBe(false)
  })

  it('says what is untrue, not just the word "mock"', async () => {
    const { MockNotice, MOCK_NOTICE } = await load('1')
    render(<MockNotice />)
    // A 10px badge reading "mock" is a label. The sentence has to be reachable
    // by someone who did not build this -- on hover and to a screen reader.
    expect(screen.getByRole('status').title).toBe(MOCK_NOTICE)
    expect(screen.getByText(MOCK_NOTICE)).toBeTruthy()
    expect(MOCK_NOTICE).toMatch(/invented/i)
  })
})

describe('the mock upload toast', () => {
  it('does not claim a document was indexed', async () => {
    // The one mock response a person acts on: a success toast saying the file
    // is in the corpus, when nothing was stored and no server was asked.
    vi.stubEnv('VITE_MOCK', '1')
    vi.resetModules()
    const { uploadFiles } = await import('@/lib/api')
    const result = await uploadFiles([new File(['x'], 'notes.pdf')])
    expect(result.success).toBe(true)
    expect(result.message).toMatch(/nothing was stored/i)
    expect(result.message).not.toMatch(/^Indexed /)
  })
})
