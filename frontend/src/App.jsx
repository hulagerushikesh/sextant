import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { checkHealth, fetchStats, streamQuery } from './api/client'
import Answer from './components/Answer'
import Corpus from './components/Corpus'
import Lab from './components/Lab'
import Opening, { MOD } from './components/Opening'
import Palette from './components/Palette'
import SourcePanel from './components/SourcePanel'
import Toast, { useToast } from './components/Toast'
import Trace from './components/Trace'
import Usage from './components/Usage'
import { blank, loadAll, remove, saveAll, upsert } from './conversations'
import { storageKey } from './storage'
import { money, readLifetime, record, resetLifetime, seedFrom, totals } from './usage'

const FIRST_RUN_KEY = storageKey('onboarded')

/**
 * Grow the composer with its content, one line to six. A fixed two-row box
 * wasted a line on every short question and still clipped a long one;
 * measuring scrollHeight after resetting the height is the whole trick.
 */
function autosize(box) {
  box.style.height = 'auto'
  box.style.height = `${Math.min(box.scrollHeight, 160)}px`
}

/**
 * The corpus figures, fetched once and shared.
 *
 * `status` separates "still asking" from "asked and got nothing": the panel
 * used to show "knowledge base unreachable" for the half-second before the
 * first reply, which is a false alarm on every page load.
 */
function useCorpus() {
  const [corpus, setCorpus] = useState({ status: 'loading', stats: null })
  const refresh = useCallback(async () => {
    const stats = await fetchStats()
    setCorpus(stats ? { status: 'ready', stats } : { status: 'failed', stats: null })
  }, [])
  useEffect(() => {
    refresh()
  }, [refresh])
  return [corpus, refresh]
}

const isEditable = (el) =>
  !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)

/**
 * Merge an incoming source list into the one we already hold.
 *
 * The server sends its whole registry on every `sources` frame, but labels
 * restored from earlier turns come back without their passage text -- only the
 * label travels between questions, not the content. Replacing the list wholesale
 * would therefore empty out passages the user can still see and click. Keep the
 * longer text for each label.
 */
function mergeSources(previous, incoming) {
  const byNumber = new Map(previous.map((source) => [source.n, source]))
  for (const source of incoming) {
    const held = byNumber.get(source.n)
    byNumber.set(
      source.n,
      held && (held.text || '').length > (source.text || '').length
        ? { ...source, text: held.text }
        : source
    )
  }
  return [...byNumber.values()].sort((a, b) => a.n - b.n)
}

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'system')
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])
  return [theme, setTheme]
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [live, setLive] = useState(null)
  const [sources, setSources] = useState([])
  const [activeSource, setActiveSource] = useState(null)
  const [draft, setDraft] = useState('')
  // Per question, and off each time it is used: leaving it on is how a testing
  // session quietly spends $14 per 1,000 searches.
  const [webSearch, setWebSearch] = useState(false)
  const [theme, setTheme] = useTheme()
  // 'chat' or 'lab'. The lab is a full-width analysis surface, not part of the
  // conversation, so it replaces the thread rather than sitting beside it.
  const [view, setView] = useState('chat')

  const [saved, setSaved] = useState(() => loadAll())
  const [activeId, setActiveId] = useState(() => loadAll()[0]?.id || blank().id)
  // Retrieval works without a key and answering does not, so the two are asked
  // about separately. A server that can search but cannot answer used to look
  // exactly like a working one.
  const [modelReady, setModelReady] = useState(null)
  // The server's daily spend cap, or null when unset. Refreshed after each
  // answer so the rail shows how much of today's budget is left.
  const [budget, setBudget] = useState(null)
  // Spend is recorded as it happens rather than summed from saved threads,
  // which are evicted and deleted; see usage.js.
  const [lifetime, setLifetime] = useState(() => readLifetime())
  const [corpus, refreshCorpus] = useCorpus()
  // The server is the authority on what it can parse. Hard-coding the list
  // here is how the two drifted apart last time.
  const [supported, setSupported] = useState([])
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [firstRun, setFirstRun] = useState(() => !localStorage.getItem(FIRST_RUN_KEY))
  const [toast, showToast] = useToast()

  // The stream writes here; `live` exists only to trigger a render. Reading the
  // final text off state in the `finally` block would read a stale closure.
  const textRef = useRef('')
  const sourcesRef = useRef([])
  const traceRef = useRef([])
  const doneRef = useRef(null)
  const abortRef = useRef(null)
  const bottomRef = useRef(null)
  const composerRef = useRef(null)
  // Set by the Corpus panel; opens its file picker from anywhere.
  const pickRef = useRef(null)

  const streaming = live !== null

  // Runs on every draft change, which also covers the two paths that set the
  // draft from outside the box: a starter click and the post-send reset.
  useEffect(() => {
    if (composerRef.current) autosize(composerRef.current)
  }, [draft])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    // On message count, not on every token: following the caret down the page
    // while text streams makes the answer unreadable.
  }, [messages.length])

  useEffect(() => {
    checkHealth().then((health) => {
      setModelReady(health ? health.model_configured : false)
      setBudget(health?.budget ?? null)
      setSupported(health?.supported_uploads || [])
    })
  }, [])

  // The tab names the conversation, so five open tabs are tellable apart.
  useEffect(() => {
    const current = saved.find((c) => c.id === activeId)
    const title = current && current.messages.length ? current.title : null
    document.title = title ? `${title} · sextant` : 'sextant'
  }, [saved, activeId])

  useEffect(() => {
    // Restore whichever conversation was most recent, so a reload continues
    // where the last one left off instead of opening an empty box.
    setLifetime(seedFrom(saved))
    const first = saved[0]
    if (first) {
      setMessages(first.messages)
      setSources(first.sources)
      sourcesRef.current = first.sources
    }
    // Deliberately once, on mount: later saves must not reload the transcript
    // out from under an answer that is still streaming.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const persist = useCallback(
    (nextMessages, nextSources) => {
      setSaved((previous) =>
        saveAll(upsert(previous, activeId, { messages: nextMessages, sources: nextSources }))
      )
    },
    [activeId]
  )

  const resolve = useCallback((n) => sources.find((source) => source.n === n), [sources])

  const showSource = useCallback((n) => {
    setActiveSource(n)
    // Let the panel expand before scrolling to it.
    requestAnimationFrame(() =>
      document.getElementById(`source-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    )
  }, [])

  const ask = useCallback(
    async (question, useWeb) => {
      const history = messages.map(({ role, text }) => ({ role, content: text }))
      setMessages((prev) => [...prev, { role: 'user', text: question }])
      textRef.current = ''
      traceRef.current = []
      doneRef.current = null
      setLive({ tick: 0 })

      const controller = new AbortController()
      abortRef.current = controller
      let stopped = false
      let error = null

      const render = () => setLive((prev) => ({ tick: (prev?.tick ?? 0) + 1 }))

      try {
        await streamQuery(question, {
          history,
          sources,
          webSearch: useWeb,
          signal: controller.signal,
          onToken: (text) => {
            textRef.current += text
            render()
          },
          onAnswer: ({ text }) => {
            // A turn that used web search, relabelled with its citations now
            // that the text is complete. Replaces what streamed rather than
            // appending: the labels are interleaved through the sentences, not
            // stacked at the end. Knowledge-base labels need none of this --
            // the model writes those itself, mid-sentence, as it goes.
            textRef.current = text
            render()
          },
          onToolCall: (call) => {
            traceRef.current = [...traceRef.current, call]
            render()
          },
          onToolResult: ({ name, summary, duration_ms: durationMs }) => {
            // Attach to the most recent call of that tool: one call, one row,
            // now with its outcome.
            const steps = [...traceRef.current]
            for (let i = steps.length - 1; i >= 0; i -= 1) {
              if (steps[i].name === name && !steps[i].summary) {
                steps[i] = { ...steps[i], summary, duration_ms: durationMs }
                break
              }
            }
            traceRef.current = steps
            render()
          },
          onSources: (incoming) =>
            setSources((prev) => {
              const merged = mergeSources(prev, incoming)
              sourcesRef.current = merged
              return merged
            }),
          onDone: (payload) => {
            doneRef.current = payload
          },
        })
      } catch (caught) {
        if (caught.name === 'AbortError') stopped = true
        else error = caught.message
      } finally {
        const done = doneRef.current
        const answer = {
          role: 'assistant',
          text: textRef.current,
          trace: traceRef.current,
          usage: done?.usage,
          turns: done?.turns,
          truncated: done?.truncated,
          stopped,
          error,
        }
        if (done?.usage) setLifetime(record(done.usage))
        setMessages((prev) => {
          const next = [...prev, answer]
          // Save once the exchange is complete, not per token: a half-written
          // answer is not a conversation worth restoring.
          persist(next, sourcesRef.current)
          return next
        })
        setLive(null)
        abortRef.current = null
        // The answer just charged the daily cap; pull the new remaining figure.
        if (done?.usage) checkHealth().then((h) => setBudget(h?.budget ?? null))
      }
    },
    [messages, sources, persist]
  )

  const submit = (event) => {
    event.preventDefault()
    const question = draft.trim()
    if (!question || streaming) return
    setDraft('')
    setWebSearch(false)
    ask(question, webSearch)
  }

  const open = (conversation) => {
    abortRef.current?.abort()
    setActiveId(conversation.id)
    setMessages(conversation.messages)
    setSources(conversation.sources)
    sourcesRef.current = conversation.sources
    setActiveSource(null)
    setLive(null)
  }

  const startNew = () => {
    // A blank conversation is not written to storage until it has a turn in it,
    // so clicking this twice does not leave two empty entries in the list.
    open(blank())
  }

  const discard = (id, event) => {
    event?.stopPropagation()
    setSaved((previous) => saveAll(remove(previous, id)))
    if (id === activeId) startNew()
    showToast('Conversation deleted')
  }

  const focusComposer = useCallback(() => {
    const box = composerRef.current
    if (!box) return
    box.focus()
    box.setSelectionRange(box.value.length, box.value.length)
  }, [])

  const toggleTheme = useCallback(
    () => setTheme(theme === 'dark' ? 'light' : 'dark'),
    [theme, setTheme]
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const lastAnswer = [...messages].reverse().find((m) => m.role === 'assistant' && m.text)
  const copyAnswer = useCallback(
    async (text) => {
      try {
        await navigator.clipboard.writeText(text)
        showToast('Answer copied')
      } catch {
        showToast('Could not copy — clipboard access was refused')
      }
    },
    [showToast]
  )

  const dismissFirstRun = useCallback(() => {
    localStorage.setItem(FIRST_RUN_KEY, '1')
    setFirstRun(false)
  }, [])

  const showFirstRun = useCallback(() => {
    localStorage.removeItem(FIRST_RUN_KEY)
    setFirstRun(true)
    setView('chat')
  }, [])

  // Questions from other threads, newest first, for the empty state.
  const recent = useMemo(() => {
    const seen = new Set()
    const out = []
    for (const conversation of saved) {
      if (conversation.id === activeId) continue
      const first = conversation.messages.find((m) => m.role === 'user')
      if (first && !seen.has(first.text)) {
        seen.add(first.text)
        out.push(first.text)
      }
      if (out.length === 3) break
    }
    return out
  }, [saved, activeId])

  // Everything the palette can do. Conditional entries are left out rather
  // than greyed: a command you cannot run is noise in a list you are searching.
  const commands = useMemo(() => {
    const list = []
    if (streaming) list.push({ id: 'stop', group: 'Conversation', label: 'Stop answering', keys: ['esc'], run: stop })
    if (messages.length || streaming)
      list.push({ id: 'new', group: 'Conversation', label: 'New conversation', keys: ['⌥', 'N'], run: startNew })
    if (lastAnswer)
      list.push({ id: 'copy', group: 'Conversation', label: 'Copy last answer', keywords: 'clipboard', run: () => copyAnswer(lastAnswer.text) })
    list.push({
      id: 'web',
      group: 'Conversation',
      label: webSearch ? 'Web search for next question: on → turn off' : 'Web search for next question: off → turn on',
      hint: 'about $0.014 per grounded question',
      keys: ['⌥', 'W'],
      keywords: 'google grounding',
      run: () => setWebSearch((on) => !on),
    })
    list.push({ id: 'focus', group: 'Conversation', label: 'Focus the question box', keys: ['/'], run: focusComposer })
    if (messages.length)
      list.push({ id: 'delete', group: 'Conversation', label: 'Delete this conversation', keywords: 'remove', run: () => discard(activeId) })

    list.push({
      id: 'view',
      group: 'View',
      label: view === 'chat' ? 'Open the Index Lab' : 'Back to Chat',
      keys: ['⌥', 'L'],
      keywords: 'ann hnsw ivfpq benchmark',
      run: () => setView((v) => (v === 'chat' ? 'lab' : 'chat')),
    })
    list.push({ id: 'theme', group: 'View', label: theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme', keys: ['⌥', 'T'], keywords: 'colour color mode', run: toggleTheme })

    list.push({ id: 'upload', group: 'Corpus', label: 'Add documents…', hint: supported.join(' '), keywords: 'upload ingest files pdf', run: () => pickRef.current?.() })
    list.push({ id: 'refresh', group: 'Corpus', label: 'Refresh corpus figures', run: refreshCorpus })

    for (const conversation of saved) {
      if (conversation.id === activeId || !conversation.messages.length) continue
      list.push({
        id: `open-${conversation.id}`,
        group: 'Conversations',
        label: conversation.title,
        hint: money(totals(conversation.messages).costUsd),
        keywords: 'open switch thread',
        run: () => open(conversation),
      })
    }

    list.push({ id: 'reset', group: 'Spend', label: 'Reset all-time spend counter', run: () => { setLifetime(resetLifetime()); showToast('All-time spend reset') } })
    list.push({ id: 'help', group: 'Help', label: 'Show getting started again', keywords: 'onboarding tour', run: showFirstRun })
    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming, messages.length, lastAnswer, webSearch, view, theme, supported, saved, activeId])

  // Keyboard, app-wide. ⌘K is the only chord that fires inside a text field;
  // everything else stays out of the way of typing.
  useEffect(() => {
    const onKey = (event) => {
      const mod = event.metaKey || event.ctrlKey
      if (mod && !event.shiftKey && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((o) => !o)
        return
      }
      if (paletteOpen) return
      if (event.key === 'Escape') {
        if (streaming) stop()
        else if (activeSource != null) setActiveSource(null)
        return
      }
      if (event.altKey && !mod) {
        const handlers = {
          KeyN: () => (messages.length || streaming) && startNew(),
          KeyW: () => !streaming && setWebSearch((on) => !on),
          KeyL: () => setView((v) => (v === 'chat' ? 'lab' : 'chat')),
          KeyT: toggleTheme,
        }
        const handler = handlers[event.code]
        if (handler) {
          event.preventDefault()
          handler()
        }
        return
      }
      if (event.key === '/' && !mod && !isEditable(event.target)) {
        event.preventDefault()
        focusComposer()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paletteOpen, streaming, activeSource, messages.length, toggleTheme])

  return (
    <div className={`shell ${view === 'lab' ? 'shell-lab' : ''}`}>
      <header className="masthead">
        <div className="masthead-name">
          <h1>sextant</h1>
          <p>
            A private corpus over MCP, and the open web, with the model choosing
            between them.
          </p>
        </div>
        <div className="masthead-controls">
          <div className="view-switch" role="tablist" aria-label="View">
            <button
              type="button"
              role="tab"
              aria-selected={view === 'chat'}
              className={view === 'chat' ? 'is-active' : ''}
              onClick={() => setView('chat')}
            >
              Chat
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'lab'}
              className={view === 'lab' ? 'is-active' : ''}
              onClick={() => setView('lab')}
            >
              Index Lab
            </button>
          </div>
          <button
            type="button"
            className="button-quiet"
            onClick={startNew}
            disabled={view === 'lab' || (!messages.length && !streaming)}
          >
            New conversation
          </button>
          <button
            type="button"
            className="button-quiet"
            onClick={toggleTheme}
            aria-label="Switch colour theme"
            title="Switch colour theme (⌥T)"
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
          <button
            type="button"
            className="button-quiet palette-trigger"
            onClick={() => setPaletteOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={paletteOpen}
            title={`Commands (${MOD}K)`}
          >
            Commands <kbd>{MOD}K</kbd>
          </button>
        </div>
      </header>

      <Palette open={paletteOpen} commands={commands} onClose={() => setPaletteOpen(false)} />
      <Toast toast={toast} />

      {view === 'lab' ? (
        <div className="lab-main">
          <Lab />
        </div>
      ) : (
      <>
      <nav className="threads" aria-label="Saved conversations">
        <h2 className="rail-heading">Conversations</h2>
        {saved.length ? (
          <ul className="thread-list">
            {saved.map((conversation) => (
              <li key={conversation.id}>
                <button
                  type="button"
                  className={`thread-item ${conversation.id === activeId ? 'is-active' : ''}`}
                  onClick={() => open(conversation)}
                >
                  <span className="thread-name">{conversation.title}</span>
                  <span className="thread-cost">{money(totals(conversation.messages).costUsd)}</span>
                  <span
                    className="thread-drop"
                    role="button"
                    tabIndex={0}
                    aria-label={`Delete ${conversation.title}`}
                    onClick={(event) => discard(conversation.id, event)}
                    onKeyDown={(event) => event.key === 'Enter' && discard(conversation.id, event)}
                  >
                    ×
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rail-empty">Conversations you have are kept in this browser.</p>
        )}
      </nav>

      <main className="thread">
        {modelReady === false && (
          <div className="banner">
            <strong>No answer will be generated.</strong> <code>GEMINI_API_KEY</code> is not
            set, so there is no model to write one. Ingestion and retrieval still work — the
            corpus panel and the source list are live. Add the key to <code>.env</code> and
            restart the server.
          </div>
        )}

        {!messages.length && !streaming && (
          <Opening
            corpus={corpus}
            recent={recent}
            onAsk={(question) => ask(question, false)}
            onAddFiles={() => pickRef.current?.()}
            firstRun={firstRun}
            onDismissFirstRun={dismissFirstRun}
          />
        )}

        <ol className="turns">
          {messages.map((message, i) =>
            message.role === 'user' ? (
              <li key={i} className="turn turn-question">
                <p>{message.text}</p>
              </li>
            ) : (
              <li key={i} className="turn turn-answer">
                <Trace steps={message.trace || []} running={false} />
                {message.text && (
                  <Answer text={message.text} resolve={resolve} onCite={showSource} />
                )}
                {message.error && <p className="notice error">{message.error}</p>}
                {message.stopped && <p className="notice">Stopped.</p>}
                {message.truncated && (
                  <p className="notice">
                    Cut off at the token limit — the answer above is incomplete.
                  </p>
                )}
                {(message.usage || message.text) && (
                  <div className="turn-foot">
                    {message.usage && (
                      <p className="ledger">
                        {message.turns} turn{message.turns === 1 ? '' : 's'} ·{' '}
                        {message.usage.input_tokens.toLocaleString()} in /{' '}
                        {message.usage.output_tokens.toLocaleString()} out ·{' '}
                        {message.usage.grounded_requests > 0 && (
                          <>
                            {message.usage.grounded_requests} web search
                            {message.usage.grounded_requests === 1 ? '' : 'es'} ·{' '}
                          </>
                        )}
                        <span title="Estimated from published per-token pricing">
                          {money(message.usage.cost_usd)}
                        </span>
                      </p>
                    )}
                    {message.text && (
                      <button
                        type="button"
                        className="turn-action"
                        onClick={() => copyAnswer(message.text)}
                      >
                        Copy
                      </button>
                    )}
                  </div>
                )}
              </li>
            )
          )}

          {streaming && (
            <li className="turn turn-answer">
              <Trace steps={traceRef.current} running />
              {textRef.current ? (
                <Answer
                  text={textRef.current}
                  resolve={resolve}
                  onCite={showSource}
                  streaming
                />
              ) : (
                // The shape of an answer, where the answer will be. Reads as
                // "coming" rather than "stuck", which a spinner never quite does.
                <div className="answer-skeleton" aria-busy="true" aria-label="Thinking">
                  <span className="skeleton" style={{ width: '92%' }} />
                  <span className="skeleton" style={{ width: '100%' }} />
                  <span className="skeleton" style={{ width: '64%' }} />
                </div>
              )}
            </li>
          )}
        </ol>

        {/* The dock is sticky and the anchor sits after it, so "scroll to the
            bottom" lands below the composer's in-flow slot and the last
            answer is never under the bar. */}
        <div className="dock">
        <form className="composer" onSubmit={submit}>
          <textarea
            ref={composerRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) submit(e)
            }}
            placeholder={
              messages.length ? 'Ask a follow-up…' : 'Ask a question about your documents…'
            }
            rows={1}
            maxLength={2000}
            aria-label="Your question"
          />
          {!streaming && (
            <button
              type="button"
              className={`web-toggle ${webSearch ? 'is-on' : ''}`}
              onClick={() => setWebSearch((on) => !on)}
              aria-pressed={webSearch}
              title="Google Search is billed per request, not per token. Off by default; this turns it on for one question."
            >
              Web {webSearch ? 'on' : 'off'}
            </button>
          )}
          {streaming ? (
            <button type="button" className="button" onClick={stop} title="Stop (esc)">
              Stop
            </button>
          ) : (
            <button type="submit" className="button" disabled={!draft.trim()}>
              Ask
            </button>
          )}
        </form>
        <p className="composer-hint">
          {streaming ? (
            <>
              <kbd>esc</kbd> to stop
            </>
          ) : (
            <>
              <kbd>↵</kbd> send · <kbd>⇧↵</kbd> new line · <kbd>/</kbd> focus · <kbd>{MOD}K</kbd>{' '}
              commands
            </>
          )}
          {webSearch && !streaming && ' · web search on for this question, about $0.014'}
        </p>
        </div>
        <div ref={bottomRef} />
      </main>

      <aside className="rail">
        <section>
          <h2 className="rail-heading">Sources</h2>
          <SourcePanel sources={sources} active={activeSource} onSelect={setActiveSource} />
        </section>
        <Usage
          conversation={totals(messages)}
          lifetime={lifetime}
          budget={budget}
          onReset={() => setLifetime(resetLifetime())}
        />
        <Corpus corpus={corpus} supported={supported} onRefresh={refreshCorpus} pickRef={pickRef} />
      </aside>
      </>
      )}
    </div>
  )
}
