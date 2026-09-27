import { useCallback, useEffect, useRef, useState } from 'react'
import { FileUp, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { uploadFiles } from '@/lib/api'
import type { Stats } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export interface CorpusState { status: 'loading' | 'ready' | 'failed'; stats: Stats | null }

/** Adding documents, and knowing whether there are any. Bytes go up untouched; the server parses. */
export function CorpusCard({ corpus, supported, onRefresh, pickRef }: { corpus: CorpusState; supported: string[]; onRefresh: () => Promise<void> | void; pickRef: React.MutableRefObject<(() => void) | null> }) {
  const { status, stats } = corpus
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { pickRef.current = () => inputRef.current?.click() }, [pickRef])

  const accept = useCallback(async (list: FileList | null) => {
    const files = Array.from(list || [])
    if (!files.length) return
    setBusy(true)
    try {
      const r = await uploadFiles(files)
      if (r.success) toast.success(r.message || 'Indexed')
      else toast.error(r.error || 'Upload failed')
      await onRefresh()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [onRefresh])

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
        <Button variant="ghost" size="icon-xs" onClick={() => onRefresh()} aria-label="Refresh corpus figures"><RefreshCw /></Button>
      </div>

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
