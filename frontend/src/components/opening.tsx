import { motion } from 'motion/react'
import { ArrowUpRight, Compass } from 'lucide-react'
import type { CorpusState } from './corpus-card'
import { MOD } from '@/lib/store'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Skeleton } from '@/components/ui/skeleton'

const STARTERS = [
  'What topics do my documents cover?',
  'Give me a one-paragraph overview of the corpus.',
  'What is the single most important idea in these documents?',
]

/**
 * The empty thread. Three states decided by what the corpus holds: still
 * finding out, nothing indexed (adding documents is the whole screen), or a
 * corpus that can be asked about.
 */
export function Opening({ corpus, recent, onAsk, onAddFiles, firstRun, onDismissFirstRun }: {
  corpus: CorpusState; recent: string[]; onAsk: (q: string) => void; onAddFiles: () => void; firstRun: boolean; onDismissFirstRun: () => void
}) {
  const loading = corpus.status === 'loading'
  const empty = corpus.status === 'ready' && !(corpus.stats && corpus.stats.documents > 0)
  const unreachable = corpus.status === 'failed'
  const fresh = STARTERS.filter((q) => !recent.includes(q))

  return (
    <div className="mx-auto w-full max-w-[68ch] pt-[8vh]">
      {firstRun && (
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }}
          aria-label="Getting started"
          className="mb-10 rounded-xl border bg-card p-5 shadow-sm"
        >
          <div className="mb-3 flex items-center gap-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            <Compass className="size-3.5 text-corpus" /> How this works
          </div>
          <ol className="grid gap-3 text-[14px] leading-relaxed sm:grid-cols-3">
            <li><strong className="block text-foreground">Add documents.</strong><span className="text-muted-foreground">Drop files on the Corpus panel, or run <code className="font-mono text-[12px]">sextant-ingest -r ./docs</code>. PDFs keep page numbers.</span></li>
            <li><strong className="block text-foreground">Ask.</strong><span className="text-muted-foreground">The agent searches your corpus first and only reaches for the web when you switch it on for a question.</span></li>
            <li><strong className="block text-foreground">Check its work.</strong><span className="text-muted-foreground">Every claim carries a numbered passage. Click a <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-[4px] border border-corpus/40 bg-corpus-muted px-1 font-mono text-[10px] text-corpus">1</span> to read what it came from.</span></li>
          </ol>
          <div className="mt-4 flex items-center justify-between">
            <span className="text-[12px] text-muted-foreground"><Kbd>{MOD}</Kbd> <Kbd>K</Kbd> opens every command</span>
            <Button variant="outline" size="sm" onClick={onDismissFirstRun}>Got it</Button>
          </div>
        </motion.section>
      )}

      {loading && (
        <div aria-busy="true" className="flex flex-col gap-3">
          <Skeleton className="h-7 w-3/5" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      )}

      {unreachable && (
        <>
          <h2 className="font-serif text-[28px] leading-tight tracking-tight">The knowledge base is not answering.</h2>
          <p className="mt-3 max-w-[54ch] text-[15px] leading-relaxed text-muted-foreground">
            The server is up but its retrieval subprocess is not. Check the server log — the usual cause is a model still downloading on first start.
          </p>
        </>
      )}

      {empty && (
        <>
          <h2 className="font-serif text-[28px] leading-tight tracking-tight">Nothing to search yet.</h2>
          <p className="mt-3 max-w-[54ch] text-[15px] leading-relaxed text-muted-foreground">
            Questions run against your own documents, and there are none indexed. Add some and the agent can start citing them.
          </p>
          <div className="mt-5 flex items-center gap-3">
            <Button onClick={onAddFiles}>Add documents</Button>
            <span className="text-[13px] text-muted-foreground">or run <code className="font-mono text-[12px]">sextant-ingest -r ./docs</code></span>
          </div>
        </>
      )}

      {corpus.status === 'ready' && !empty && (
        <>
          <h2 className="font-serif text-[30px] leading-tight tracking-tight">Ask something your documents can answer.</h2>
          <p className="mt-3 max-w-[56ch] text-[15px] leading-relaxed text-muted-foreground">
            <span className="font-mono text-[13.5px] text-foreground tabular">{corpus.stats!.documents.toLocaleString()}</span> documents,{' '}
            <span className="font-mono text-[13.5px] text-foreground tabular">{corpus.stats!.collection_size.toLocaleString()}</span> passages indexed.
            An empty answer is a real answer here — retrieval that finds nothing says so instead of filling in from memory.
          </p>

          {recent.length > 0 && <Starters heading="Pick up where you left off" items={recent} onAsk={onAsk} />}
          {fresh.length > 0 && <Starters heading={recent.length ? 'Or start fresh' : 'Try one of these'} items={fresh} onAsk={onAsk} />}
        </>
      )}
    </div>
  )
}

function Starters({ heading, items, onAsk }: { heading: string; items: string[]; onAsk: (q: string) => void }) {
  return (
    <div className="mt-7">
      <h3 className="mb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{heading}</h3>
      <ul className="flex flex-col gap-1">
        {items.map((q, i) => (
          <motion.li key={q} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i, duration: 0.25 }}>
            <button
              type="button"
              onClick={() => onAsk(q)}
              className="group flex w-full items-center justify-between gap-3 rounded-lg border border-transparent px-3 py-2 text-left text-[14px] text-foreground/90 transition-colors hover:border-border hover:bg-card"
            >
              <span>{q}</span>
              <ArrowUpRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          </motion.li>
        ))}
      </ul>
    </div>
  )
}
