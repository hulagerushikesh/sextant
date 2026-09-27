/**
 * A conversation as a Markdown file.
 *
 * Conversations live in one browser's localStorage (`store.ts`), which is fine
 * until you want one somewhere else: in a note, a ticket, a message to whoever
 * wrote the document. The answers are already Markdown -- that is what the
 * model writes and what `answer.tsx` renders -- so the export is the transcript
 * with its citations resolved into a source list, not a rendering of the page.
 *
 * Citation labels stay as `[3]`; the sources section at the end says what each
 * one was. That is the same shape the answer had on screen, and it keeps the
 * file honest about which passage each claim rests on.
 *
 * Ported from the current UI's `export.js`; the output is byte-for-byte the
 * same, because a file people already keep should not change shape under them.
 */

import type { Conversation, Message, Source } from './types'
import { money, totals } from './store'

const ORIGIN: Record<string, string> = { knowledge_base: 'corpus', web: 'web' }

function source(s: Source): string {
  const title = s.url ? `[${s.title || s.url}](${s.url})` : s.title
  return `${s.n}. ${title}${s.location ? ` (${s.location})` : ''} · ${ORIGIN[s.origin] || s.origin}`
}

function answer(message: Message): string {
  if (message.error) return `_Failed: ${message.error}_`
  const text = message.text.trim() || '_No answer._'
  const notes: string[] = []
  if (message.stopped) notes.push('stopped before it finished')
  if (message.truncated) notes.push('hit the search limit')
  return notes.length ? `${text}\n\n_(${notes.join('; ')})_` : text
}

export function toMarkdown(conversation: Conversation): string {
  const { title, messages, sources, createdAt } = conversation
  const lines = [`# ${title}`, '', `_${new Date(createdAt).toISOString().slice(0, 10)} · sextant_`, '']

  for (const message of messages) {
    if (message.role === 'user') {
      lines.push(`## ${message.text.trim()}`, '')
    } else {
      lines.push(answer(message), '')
    }
  }

  if (sources.length) {
    lines.push('## Sources', '', ...sources.map(source), '')
  }

  const spent = totals(messages)
  if (spent.questions) {
    lines.push('---', '', `${spent.questions} answered · ${money(spent.costUsd)}`, '')
  }
  return lines.join('\n')
}

/** `title` as a file name: ascii, dashes, capped. */
export function fileName(conversation: Conversation): string {
  const slug = conversation.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 48)
  return `${slug || 'conversation'}.md`
}

/** Hands the browser a file to save. No server round trip; the text is here. */
export function download(name: string, text: string): void {
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  // Revoke after the click has been handled; revoking synchronously races it.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
