import { useCallback, useEffect, useRef, useState } from 'react'
import { FileUp, RefreshCw, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { fetchDocuments, forgetDocument, uploadFiles } from '@/lib/api'
import type { DocumentSummary, Stats } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export interface CorpusState { status: 'loading' | 'ready' | 'failed'; stats: Stats | null }

/** Adding documents, and knowing whether there are any. Bytes go up untouched; the server parses. */
export function CorpusCard({ corpus, supported, onRefresh, pickRef }: { corpus: CorpusState; supported: string[]; onRefresh: () => Promise<void> | void; pickRef: React.MutableRefObject<(() => void) | null> }) {
  const { status, stats } = corpus
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null)
  // The id waiting on a second click. A destructive control in a list of
  // similar rows gets one, and asking in the row rather than in a modal keeps
  // what is about to go next to the question about it.
  const [confirming, setConfirming] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { pickRef.current = () => inputRef.current?.click() }, [pickRef])

  const reload = useCallback(async () => {
    const listing = await fetchDocuments()
    setDocuments(listing?.documents ?? null)
  }, [])

  // `reload` awaits the server before it sets anything, so this is not a
  // synchronous setState inside an effect; listing the documents on mount is
  // what an effect is for. Same judgement as `useCorpus` in App.tsx.
  // oxlint-disable-next-line react/set-state-in-effect -- the set is post-await
  useEffect(() => { void reload() }, [reload])

  const accept = useCallback(async (list: FileList | null) => {
    const files = Array.from(list || [])
    if (!files.length) return
    setBusy(true)
    try {
      const r = await uploadFiles(files)
      if (r.success) toast.success(r.message || 'Indexed')
      else toast.error(r.error || 'Upload failed')
      await onRefresh()
      await reload()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [onRefresh, reload])

  const forget = useCallback(async (doc: DocumentSummary) => {
    setConfirming(null)
    try {
      const r = await forgetDocument(doc.id)
      // The server's own sentence, which carries the chunk count. A cheerful
      // "Removed" of our own would survive a reply that said otherwise.
      toast.success(r.message || `Removed ${doc.title}`)
    } catch (e) {
      // A 403 means the server disagrees about whose document this is and a
      // 404 that it was already gone -- both worth reading, neither a crash.
      toast.error((e as Error).message)
    }
    await onRefresh()
    await reload()
  }, [onRefresh, reload])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        {status === 'loading' && <Skeleton className="h-4 w-32" />}
        {status === 'failed' && <span className="text-[13px] text-destructive">Knowledge base unreachable</span>}
        {status === 'ready' && (
          <p className="font-mono text-[12px] text-muted-foreground tabular">
            <span className="text-foreground font-medium">{stats?.documents ?? 0}</span> documents · <span className="text-foreground font-medium">{(stats?.collection_size ?? 0).toLocaleString()}</span> chunks
          </p>
        )}
        <Button variant="ghost" size="icon-xs" onClick={() => { void onRefresh(); void reload() }} aria-label="Refresh corpus figures"><RefreshCw /></Button>
      </div>

      {!!documents?.length && (
        <ul className="flex flex-col divide-y divide-border rounded-lg border border-border">
          {documents.map((doc) => (
            <li key={doc.id} className="flex items-center gap-2 px-2.5 py-1.5">
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-foreground" title={doc.title || doc.id}>
                {doc.title || doc.id}
              </span>
              <span className="font-mono text-[10.5px] text-muted-foreground tabular">{doc.chunks}</span>
              {/* Drawn from `yours`, which is the server's own answer to "may I
                  remove this?" -- never from the id's prefix, which is wrong
                  behind the gate, where the owner is the name the proxy
                  vouched for rather than this browser's client id. */}
              {doc.yours && (
                confirming === doc.id ? (
                  <span className="flex items-center gap-1">
                    <Button variant="destructive" size="xs" onClick={() => void forget(doc)}>Remove</Button>
                    <Button variant="ghost" size="xs" onClick={() => setConfirming(null)}>Cancel</Button>
                  </span>
                ) : (
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => setConfirming(doc.id)}
                    aria-label={`Remove ${doc.title || doc.id}`}
                  >
                    <X />
                  </Button>
                )
              )}
            </li>
          ))}
        </ul>
      )}

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); accept(e.dataTransfer.files) }}
        className={cn(
          'flex flex-col items-center gap-1.5 rounded-lg border border-dashed px-3 py-4 text-center transition-colors',
          dragging ? 'border-corpus bg-corpus-muted' : 'border-border',
          busy && 'opacity-70',
        )}
      >
        <input ref={inputRef} type="file" multiple className="sr-only" accept={supported.join(',')} onChange={(e) => { accept(e.target.files); e.target.value = '' }} />
        <FileUp className={cn('size-4', dragging ? 'text-corpus' : 'text-muted-foreground')} />
        <p className="text-[12.5px] text-foreground">{busy ? 'Parsing and embedding…' : 'Drop files, or'}</p>
        {!busy && <Button variant="outline" size="xs" onClick={() => inputRef.current?.click()}>Choose files</Button>}
        {!!supported.length && <p className="font-mono text-[10.5px] text-muted-foreground">{supported.join(' · ')}</p>}
      </div>

      {stats?.embedding_model && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
          <dt className="text-muted-foreground">embed</dt><dd className="truncate text-foreground">{stats.embedding_model}</dd>
          <dt className="text-muted-foreground">rerank</dt><dd className="truncate text-foreground">{stats.reranker}</dd>
          <dt className="text-muted-foreground">chunk</dt><dd className="text-foreground">{stats.chunking?.target_tokens} tok · {stats.chunking?.overlap_tokens} overlap</dd>
        </dl>
      )}
    </div>
  )
}
