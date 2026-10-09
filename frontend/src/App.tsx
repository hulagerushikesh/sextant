import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Command as CommandIcon, Copy, Moon, PanelRight, Sun } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { checkHealth, fetchStats, MOCK, streamQuery } from '@/lib/api'
import { blank, loadAll, MOD, money, readLifetime, record, remove, resetLifetime, saveAll, seedFrom, totals, upsert } from '@/lib/store'
import { storageKey } from '@/lib/storage'
import { download, fileName, toMarkdown } from '@/lib/export'
import type { Budget, Conversation, DoneFrame, Message, Source, TraceStep } from '@/lib/types'

// The Index Lab is the only view that pulls Recharts, and it is a benchmark
// nobody opens on the way to asking a question. Splitting it keeps the chart
// library off the path to the first answer.
const Lab = lazy(() => import('@/components/lab/lab').then((m) => ({ default: m.Lab })))

// cmdk and the dialog it lives in are worth nothing until someone presses
// ⌘K, so they load then. Mounting only while open also means the fallback
// can be nothing: there is no layout to hold.
const CommandPalette = lazy(() => import('@/components/command-palette').then((m) => ({ default: m.CommandPalette })))
import { useTheme } from '@/hooks/use-theme'
import { Answer } from '@/components/answer'
import { AppSidebar, type View } from '@/components/app-sidebar'
import type { CommandSpec } from '@/components/command-palette'
import { Composer } from '@/components/composer'
import { CorpusCard, type CorpusState } from '@/components/corpus-card'
import { Opening } from '@/components/opening'
import { SourceList } from '@/components/source-list'
import { SpendCard } from '@/components/spend-card'
import { Trace } from '@/components/trace'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { Skeleton } from '@/components/ui/skeleton'
import { Toaster } from '@/components/ui/sonner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const FIRST_RUN_KEY = storageKey('onboarded')
const isEditable = (el: EventTarget | null) =>
  !!el && el instanceof HTMLElement && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)

/** Merge an incoming source list, keeping the longer passage text per label. */
function mergeSources(prev: Source[], incoming: Source[]) {
  const by = new Map(prev.map((s) => [s.n, s]))
  for (const s of incoming) {
    const held = by.get(s.n)
    by.set(s.n, held && (held.text || '').length > (s.text || '').length ? { ...s, text: held.text } : s)
  }
  return [...by.values()].sort((a, b) => a.n - b.n)
}

function useCorpus(): [CorpusState, () => Promise<void>] {
  const [corpus, setCorpus] = useState<CorpusState>({ status: 'loading', stats: null })
  const refresh = useCallback(async () => {
    const stats = await fetchStats()
    setCorpus(stats ? { status: 'ready', stats } : { status: 'failed', stats: null })
  }, [])
  // oxlint-disable-next-line react/set-state-in-effect -- `refresh` awaits the
  // server before it sets anything, so this is not a synchronous setState in an
  // effect; fetching on mount is what an effect is for.
  useEffect(() => { refresh() }, [refresh])
  return [corpus, refresh]
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [live, setLive] = useState<{ tick: number } | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [activeSource, setActiveSource] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [webSearch, setWebSearch] = useState(false)
  const { resolved: theme, toggle: toggleTheme } = useTheme()
  const [view, setView] = useState<View>('chat')
  const [saved, setSaved] = useState<Conversation[]>(() => loadAll())
  const [activeId, setActiveId] = useState(() => loadAll()[0]?.id || blank().id)
  const [modelReady, setModelReady] = useState<boolean | null>(null)
  const [health, setHealth] = useState<'ok' | 'degraded' | 'down' | null>(null)
  const [budget, setBudget] = useState<Budget | null>(null)
  const [lifetime, setLifetime] = useState(() => readLifetime())
  const [corpus, refreshCorpus] = useCorpus()
  const [supported, setSupported] = useState<string[]>([])
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [railOpen, setRailOpen] = useState(false)
  const [firstRun, setFirstRun] = useState(() => !localStorage.getItem(FIRST_RUN_KEY))

  const textRef = useRef('')
  const sourcesRef = useRef<Source[]>([])
  const traceRef = useRef<TraceStep[]>([])
  const doneRef = useRef<DoneFrame | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const pickRef = useRef<(() => void) | null>(null)

  const streaming = live !== null

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages.length])

  useEffect(() => {
    checkHealth().then((h) => {
      setModelReady(h ? h.model_configured : false)
      setHealth(!h ? 'down' : h.model_configured && h.mcp_connected ? 'ok' : 'degraded')
      setBudget(h?.budget ?? null)
      setSupported(h?.supported_uploads || [])
    })
  }, [])

  useEffect(() => {
    const current = saved.find((c) => c.id === activeId)
    const title = current && current.messages.length ? current.title : null
    document.title = title ? `${title} · Sextant` : 'Sextant'
  }, [saved, activeId])

  useEffect(() => {
    setLifetime(seedFrom(saved))
    const first = saved[0]
    if (first) { setMessages(first.messages); setSources(first.sources); sourcesRef.current = first.sources }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- restoring the
    // last conversation is a mount-only act. Depending on `saved` would reopen
    // the newest thread every time one is saved, discarding what is on screen.
  }, [])

  const persist = useCallback((m: Message[], s: Source[]) => {
    setSaved((prev) => saveAll(upsert(prev, activeId, { messages: m, sources: s })))
  }, [activeId])

  const resolve = useCallback((n: number) => sources.find((s) => s.n === n), [sources])

  const showSource = useCallback((n: number) => {
    setActiveSource(n)
    if (window.innerWidth < 1280) setRailOpen(true)
    requestAnimationFrame(() => document.getElementById(`source-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
  }, [])

  const ask = useCallback(async (question: string, useWeb: boolean) => {
    const history = messages.map(({ role, text }) => ({ role, content: text }))
    setMessages((prev) => [...prev, { role: 'user', text: question }])
    textRef.current = ''; traceRef.current = []; doneRef.current = null
    setLive({ tick: 0 })
    const controller = new AbortController()
    abortRef.current = controller
    let stopped = false
    let error: string | null = null
    const render = () => setLive((p) => ({ tick: (p?.tick ?? 0) + 1 }))
    try {
      await streamQuery(question, {
        history, sources, webSearch: useWeb, signal: controller.signal,
        onToken: (t) => { textRef.current += t; render() },
        onAnswer: ({ text }) => { textRef.current = text; render() },
        onToolCall: (call) => { traceRef.current = [...traceRef.current, call]; render() },
        onToolResult: ({ name, summary, duration_ms }) => {
          const steps = [...traceRef.current]
          for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].name === name && !steps[i].summary) { steps[i] = { ...steps[i], summary, duration_ms }; break }
          }
          traceRef.current = steps; render()
        },
        onSources: (incoming) => setSources((prev) => { const m = mergeSources(prev, incoming); sourcesRef.current = m; return m }),
        onDone: (d) => { doneRef.current = d },
      })
    } catch (e) {
      if ((e as Error).name === 'AbortError') stopped = true
      else error = (e as Error).message
    } finally {
      const done = doneRef.current as DoneFrame | null
      const answer: Message = { role: 'assistant', text: textRef.current, trace: traceRef.current, usage: done?.usage, turns: done?.turns, truncated: done?.truncated, stopped, error }
      if (done?.usage) setLifetime(record(done.usage))
      setMessages((prev) => { const next = [...prev, answer]; persist(next, sourcesRef.current); return next })
      setLive(null)
      abortRef.current = null
      if (done?.usage) checkHealth().then((h) => setBudget(h?.budget ?? null))
    }
  }, [messages, sources, persist])

  const submit = () => {
    const q = draft.trim()
    if (!q || streaming) return
    setDraft(''); setWebSearch(false)
    ask(q, webSearch)
  }

  const open = (c: Conversation) => {
    abortRef.current?.abort()
    setActiveId(c.id); setMessages(c.messages); setSources(c.sources); sourcesRef.current = c.sources
    setActiveSource(null); setLive(null); setView('chat')
  }
  const startNew = () => open(blank())
  const discard = (id: string) => {
    setSaved((prev) => saveAll(remove(prev, id)))
    if (id === activeId) startNew()
    toast('Conversation deleted')
  }

  const focusComposer = useCallback(() => {
    const box = composerRef.current
    if (!box) return
    box.focus(); box.setSelectionRange(box.value.length, box.value.length)
  }, [])
  const stop = useCallback(() => abortRef.current?.abort(), [])
  const lastAnswer = [...messages].reverse().find((m) => m.role === 'assistant' && m.text)
  const copyAnswer = useCallback(async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast.success('Answer copied') } catch { toast.error('Clipboard access was refused') }
  }, [])
  // The saved copy is the source of truth for title and createdAt; the live
  // messages and sources are newer than the last write, so they win.
  const exportConversation = useCallback(() => {
    const current = saved.find((c) => c.id === activeId) || blank()
    download(fileName(current), toMarkdown({ ...current, messages, sources }))
    toast.success('Conversation exported')
  }, [saved, activeId, messages, sources])
  const dismissFirstRun = useCallback(() => { localStorage.setItem(FIRST_RUN_KEY, '1'); setFirstRun(false) }, [])
  const showFirstRun = useCallback(() => { localStorage.removeItem(FIRST_RUN_KEY); setFirstRun(true); setView('chat') }, [])

  const recent = useMemo(() => {
    const seen = new Set<string>(); const out: string[] = []
    for (const c of saved) {
      if (c.id === activeId) continue
      const first = c.messages.find((m) => m.role === 'user')
      if (first && !seen.has(first.text)) { seen.add(first.text); out.push(first.text) }
      if (out.length === 3) break
    }
    return out
  }, [saved, activeId])

  const commands = useMemo<CommandSpec[]>(() => {
    const list: CommandSpec[] = []
    if (streaming) list.push({ id: 'stop', group: 'Conversation', label: 'Stop answering', keys: ['esc'], run: stop })
    if (messages.length || streaming) list.push({ id: 'new', group: 'Conversation', label: 'New conversation', keys: ['⌥', 'N'], run: startNew })
    if (lastAnswer) list.push({ id: 'copy', group: 'Conversation', label: 'Copy last answer', keywords: 'clipboard', run: () => copyAnswer(lastAnswer.text) })
    list.push({ id: 'web', group: 'Conversation', label: webSearch ? 'Turn web search off' : 'Turn web search on for next question', hint: '~$0.014 per grounded question', keys: ['⌥', 'W'], keywords: 'google grounding', run: () => setWebSearch((o) => !o) })
    list.push({ id: 'focus', group: 'Conversation', label: 'Focus the question box', keys: ['/'], run: focusComposer })
    if (messages.length) list.push({ id: 'export', group: 'Conversation', label: 'Export as Markdown', hint: '.md, with sources', keywords: 'download save file', run: exportConversation })
    if (messages.length) list.push({ id: 'delete', group: 'Conversation', label: 'Delete this conversation', keywords: 'remove', run: () => discard(activeId) })
    list.push({ id: 'view', group: 'View', label: view === 'chat' ? 'Open the Index Lab' : 'Back to Chat', keys: ['⌥', 'L'], keywords: 'ann hnsw ivfpq benchmark', run: () => setView((v) => (v === 'chat' ? 'lab' : 'chat')) })
    list.push({ id: 'theme', group: 'View', label: theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme', keys: ['⌥', 'T'], keywords: 'colour color mode', run: toggleTheme })
    list.push({ id: 'upload', group: 'Corpus', label: 'Add documents…', hint: supported.join(' '), keywords: 'upload ingest files pdf', run: () => pickRef.current?.() })
    list.push({ id: 'refresh', group: 'Corpus', label: 'Refresh corpus figures', run: refreshCorpus })
    for (const c of saved) {
      if (c.id === activeId || !c.messages.length) continue
      list.push({ id: `open-${c.id}`, group: 'Conversations', label: c.title, hint: money(totals(c.messages).costUsd), keywords: 'open switch thread', run: () => open(c) })
    }
    list.push({ id: 'reset', group: 'Spend', label: 'Reset all-time spend counter', run: () => { setLifetime(resetLifetime()); toast('All-time spend reset') } })
    list.push({ id: 'help', group: 'Help', label: 'Show getting started again', keywords: 'onboarding tour', run: showFirstRun })
    return list
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the listed deps
    // are the values that change what the palette offers. The `run` callbacks
    // it closes over (`open`, `showFirstRun`, `refreshCorpus`, the refs) are
    // stable by construction, and naming them would rebuild every entry on
    // every render for no change in the list.
  }, [streaming, messages.length, lastAnswer, webSearch, view, theme, supported, saved, activeId, exportConversation])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && !e.shiftKey && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen((o) => !o); return }
      if (paletteOpen) return
      if (e.key === 'Escape') { if (streaming) stop(); else if (activeSource != null) setActiveSource(null); return }
      if (e.altKey && !mod) {
        const handlers: Record<string, () => void> = {
          KeyN: () => { if (messages.length || streaming) startNew() },
          KeyW: () => { if (!streaming) setWebSearch((o) => !o) },
          KeyL: () => setView((v) => (v === 'chat' ? 'lab' : 'chat')),
          KeyT: toggleTheme,
        }
        const h = handlers[e.code]
        if (h) { e.preventDefault(); h() }
        return
      }
      if (e.key === '/' && !mod && !isEditable(e.target)) { e.preventDefault(); focusComposer() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps are the
    // values the handlers read when a key arrives. The rest are stable
    // callbacks and refs; adding them would detach and reattach a window
    // listener on most renders.
  }, [paletteOpen, streaming, activeSource, messages.length, toggleTheme])

  const rail = (
    <div className="flex flex-col gap-6 p-4">
      <section>
        <RailHeading>Sources {sources.length > 0 && <span className="ml-1 font-mono text-[10.5px] text-muted-foreground tabular">{sources.length}</span>}</RailHeading>
        <SourceList sources={sources} active={activeSource} onSelect={setActiveSource} />
      </section>
      <Separator />
      <section>
        <RailHeading>Spend</RailHeading>
        <SpendCard conversation={totals(messages)} lifetime={lifetime} budget={budget} onReset={() => { setLifetime(resetLifetime()); toast('All-time spend reset') }} />
      </section>
      <Separator />
      <section>
        <RailHeading>Corpus</RailHeading>
        <CorpusCard corpus={corpus} supported={supported} onRefresh={refreshCorpus} pickRef={pickRef} />
      </section>
    </div>
  )

  return (
    <SidebarProvider className="h-full">
      <AppSidebar view={view} onView={setView} conversations={saved} activeId={activeId} onOpen={open} onNew={startNew} onDelete={discard} health={health} />
      <SidebarInset className="h-svh min-h-0 overflow-hidden">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 !h-4" />
          <span className="min-w-0 truncate text-[13px] font-medium">{view === 'lab' ? 'Index Lab' : (saved.find((c) => c.id === activeId)?.messages.length ? saved.find((c) => c.id === activeId)!.title : 'New conversation')}</span>
          {MOCK && <Badge variant="outline" className="ml-1 hidden h-5 font-mono text-[10px] text-muted-foreground sm:inline-flex">mock</Badge>}
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="sm" onClick={() => setPaletteOpen(true)} aria-haspopup="dialog" aria-label="Commands" className="gap-1.5 text-muted-foreground">
                  <CommandIcon className="size-3.5" /> <span className="hidden sm:inline">Commands</span> <Kbd className="ml-0.5 hidden sm:inline-flex">{MOD}K</Kbd>
                </Button>
              </TooltipTrigger>
              <TooltipContent>Every action, from the keyboard</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" onClick={toggleTheme} aria-label="Switch colour theme">
                  {theme === 'dark' ? <Sun /> : <Moon />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>Theme <span className="ml-1 font-mono text-[10px] opacity-70">⌥T</span></TooltipContent>
            </Tooltip>
            {view === 'chat' && (
              <Button variant="ghost" size="icon-sm" onClick={() => setRailOpen(true)} aria-label="Open sources panel" className="xl:hidden">
                <PanelRight />
              </Button>
            )}
          </div>
        </header>

        {paletteOpen && (
          <Suspense fallback={null}>
            <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} commands={commands} />
          </Suspense>
        )}
        <Toaster position="bottom-center" />

        {view === 'lab' ? (
          <ScrollArea className="min-h-0 flex-1">
            <Suspense fallback={
              <div className="mx-auto w-full max-w-5xl space-y-3 p-6" aria-busy="true" aria-label="Loading the Index Lab">
                <Skeleton className="h-8 w-56" /><Skeleton className="h-4 w-80" /><Skeleton className="h-64 w-full" />
              </div>
            }>
              <Lab />
            </Suspense>
          </ScrollArea>
        ) : (
          <div className="flex min-h-0 flex-1">
            <main className="flex min-w-0 flex-1 flex-col">
              <ScrollArea className="min-h-0 flex-1">
                <div className="mx-auto w-full max-w-[76ch] px-6 pt-6 pb-4">
                  {modelReady === false && (
                    <div className="mb-6 rounded-lg border border-web/40 bg-web-muted px-3.5 py-2.5 text-[13px] leading-relaxed">
                      <strong>No answer will be generated.</strong> <code className="font-mono text-[12px]">GEMINI_API_KEY</code> is not set. Ingestion and retrieval still work. Add the key to <code className="font-mono text-[12px]">.env</code> and restart the server.
                    </div>
                  )}

                  {!messages.length && !streaming && (
                    <Opening corpus={corpus} recent={recent} onAsk={(q) => ask(q, false)} onAddFiles={() => pickRef.current?.()} firstRun={firstRun} onDismissFirstRun={dismissFirstRun} />
                  )}

                  <ol className="flex flex-col gap-8">
                    <AnimatePresence initial={false}>
                      {messages.map((m, i) =>
                        m.role === 'user' ? (
                          <motion.li key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22 }} className="flex justify-end">
                            <p className="max-w-[60ch] rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-[15px] leading-relaxed">{m.text}</p>
                          </motion.li>
                        ) : (
                          <motion.li key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.22 }} className="group/turn">
                            <Trace steps={m.trace || []} running={false} />
                            {m.text && <Answer text={m.text} resolve={resolve} onCite={showSource} active={activeSource} />}
                            {m.error && <p className="mt-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] text-destructive">{m.error}</p>}
                            {m.stopped && <p className="mt-2 text-[13px] text-muted-foreground">Stopped.</p>}
                            {m.truncated && <p className="mt-2 text-[13px] text-muted-foreground">Cut off at the token limit — the answer above is incomplete.</p>}
                            {(m.usage || m.text) && (
                              <div className="mt-3 flex items-center gap-3 text-[11.5px] text-muted-foreground">
                                {m.usage && (
                                  <span className="font-mono tabular">
                                    {m.turns} turn{m.turns === 1 ? '' : 's'} · {m.usage.input_tokens.toLocaleString()} in / {m.usage.output_tokens.toLocaleString()} out
                                    {m.usage.grounded_requests > 0 && <> · <span className="text-web">{m.usage.grounded_requests} web</span></>}
                                    {' · '}<span title="Estimated from published per-token pricing">{money(m.usage.cost_usd)}</span>
                                  </span>
                                )}
                                {m.text && (
                                  <Button variant="ghost" size="xs" onClick={() => copyAnswer(m.text)} className="gap-1 text-muted-foreground opacity-0 transition-opacity group-hover/turn:opacity-100 focus-visible:opacity-100">
                                    <Copy /> Copy
                                  </Button>
                                )}
                              </div>
                            )}
                          </motion.li>
                        ),
                      )}
                    </AnimatePresence>

                    {streaming && (
                      <li>
                        <Trace steps={traceRef.current} running />
                        {textRef.current ? (
                          <Answer text={textRef.current} resolve={resolve} onCite={showSource} streaming active={activeSource} />
                        ) : (
                          <div aria-busy="true" aria-label="Thinking" className="flex flex-col gap-2.5 pt-1">
                            <Skeleton className="h-4 w-[92%]" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-[64%]" />
                          </div>
                        )}
                      </li>
                    )}
                  </ol>
                  <div ref={bottomRef} className="h-2" />
                </div>
              </ScrollArea>

              <div className="shrink-0 border-t bg-background/80 px-6 pt-3 pb-3 backdrop-blur supports-[backdrop-filter]:bg-background/60">
                <Composer ref={composerRef} value={draft} onChange={setDraft} onSubmit={submit} onStop={stop} streaming={streaming} webSearch={webSearch} onToggleWeb={() => setWebSearch((o) => !o)} hasMessages={messages.length > 0} />
              </div>
            </main>

            <aside className={cn('hidden w-[21rem] shrink-0 border-l bg-sidebar/40 xl:block')}>
              <ScrollArea className="h-full scrollbar-thin">{rail}</ScrollArea>
            </aside>

            <Sheet open={railOpen} onOpenChange={setRailOpen}>
              <SheetContent side="right" className="w-[22rem] p-0 sm:max-w-[22rem]">
                <SheetTitle className="sr-only">Sources, spend and corpus</SheetTitle>
                <ScrollArea className="h-full">{rail}</ScrollArea>
              </SheetContent>
            </Sheet>
          </div>
        )}
      </SidebarInset>
    </SidebarProvider>
  )
}

function RailHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-2.5 flex items-center text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{children}</h2>
}
