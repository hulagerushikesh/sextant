/**
 * The Markdown a person keeps.
 *
 * The header used to promise this was byte-for-byte what an `export.js` that
 * no longer exists produced, which is a promise nobody can check against a
 * file nobody can open. These pin the shape directly: that is what the
 * promise was for.
 */
import { describe, expect, it } from 'vitest'
import { fileName, toMarkdown } from './export'
import type { Conversation } from './types'

const conversation = (over: Partial<Conversation> = {}): Conversation => ({
  id: 'c1',
  title: 'Why is the index slow',
  createdAt: Date.UTC(2026, 9, 24, 12, 0, 0),
  updatedAt: Date.UTC(2026, 9, 24, 12, 0, 0),
  messages: [
    { role: 'user', text: 'Why is the index slow?' },
    {
      role: 'assistant',
      text: 'Because IVF-PQ probes too few lists [1].',
      usage: { input_tokens: 10, output_tokens: 20, grounded_requests: 1, cost_usd: 0.0042 },
    },
  ],
  sources: [
    { n: 1, key: 'k1', origin: 'knowledge_base', title: 'Tuning notes', location: 'p. 4' },
  ],
  ...over,
})

describe('the transcript keeps its citations attached', () => {
  it('leaves the citation label in the answer and resolves it at the end', () => {
    const md = toMarkdown(conversation())
    expect(md).toContain('[1]')
    expect(md).toContain('## Sources')
    expect(md).toContain('1. Tuning notes (p. 4) · corpus')
  })

  it('links a web source and names its origin', () => {
    const md = toMarkdown(conversation({
      sources: [{ n: 2, key: 'k2', origin: 'web', title: 'A page', url: 'https://example.com/a' }],
    }))
    expect(md).toContain('2. [A page](https://example.com/a) · web')
  })

  it('says a turn failed rather than exporting an empty answer', () => {
    const md = toMarkdown(conversation({
      messages: [{ role: 'user', text: 'q' }, { role: 'assistant', text: '', error: 'upstream 503' }],
    }))
    expect(md).toContain('_Failed: upstream 503_')
  })

  it('marks a turn that was stopped or hit the search limit', () => {
    const md = toMarkdown(conversation({
      messages: [{ role: 'user', text: 'q' }, { role: 'assistant', text: 'partial', stopped: true, truncated: true }],
    }))
    expect(md).toContain('stopped before it finished')
    expect(md).toContain('hit the search limit')
  })

  it('omits the sources section when there were none', () => {
    expect(toMarkdown(conversation({ sources: [] }))).not.toContain('## Sources')
  })

  it('omits the footer when no turn carried usage', () => {
    const md = toMarkdown(conversation({
      messages: [{ role: 'user', text: 'q' }, { role: 'assistant', text: 'a' }],
    }))
    expect(md).not.toContain('answered ·')
  })

  it('reports the spend of the turns it exported', () => {
    expect(toMarkdown(conversation())).toContain('1 answered · $0.0042')
  })
})

describe('the file name', () => {
  it('is ascii, dashed and capped', () => {
    const name = fileName(conversation({ title: 'Why is the Index  SLOW?? — notes' }))
    expect(name).toMatch(/^[a-z0-9-]+\.md$/)
    expect(name.length).toBeLessThanOrEqual(51)
  })

  it('falls back rather than producing a dotfile', () => {
    // A title of nothing but punctuation slugs to the empty string, and
    // `.md` alone is a hidden file with no name.
    expect(fileName(conversation({ title: '— ?! —' }))).toBe('conversation.md')
  })
})
