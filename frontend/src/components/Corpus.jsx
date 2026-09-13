import React, { useCallback, useEffect, useRef, useState } from 'react'
import { uploadFiles } from '../api/client'

/**
 * Adding documents, and knowing whether there are any.
 *
 * What this replaced first: three chained `window.prompt()` calls, so the only
 * way to add a document was to paste its whole text into a browser dialog.
 *
 * What it replaced second, and the more interesting mistake: reading files in
 * the browser. That limited uploads to formats JavaScript can read as text,
 * which meant PDFs -- the format people actually have -- were refused with a
 * note to go run a terminal command. The bytes now go to the server untouched
 * and the loaders that already knew how to read a PDF do the work, so a dropped
 * PDF keeps its page numbers and its citations say "p. 14".
 *
 * The corpus figures themselves live in App (see useCorpus): the empty thread
 * needs them to decide what to show, and one fetch feeding two panels beats two
 * panels that can disagree.
 */

export default function Corpus({ corpus, supported, onRefresh, pickRef }) {
  const { status, stats } = corpus
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState(null)
  const inputRef = useRef(null)

  // Let the empty state and the palette open the file picker from outside.
  useEffect(() => {
    if (pickRef) pickRef.current = () => inputRef.current?.click()
  }, [pickRef])

  const accept = useCallback(
    async (fileList) => {
      const files = Array.from(fileList)
      if (!files.length) return

      setBusy(true)
      setReport(null)
      try {
        const result = await uploadFiles(files)
        setReport({
          tone: result.success ? 'ok' : 'error',
          message: result.success ? result.message : result.error,
        })
        await onRefresh()
      } catch (error) {
        setReport({ tone: 'error', message: error.message })
      } finally {
        setBusy(false)
      }
    },
    [onRefresh]
  )

  return (
    <section className="corpus">
      <h2 className="rail-heading">Corpus</h2>

      <p className="corpus-size">
        {status === 'loading' && (
          <span className="skeleton" style={{ width: '70%' }} aria-label="Loading corpus size" />
        )}
        {status === 'failed' && <span className="is-absent">knowledge base unreachable</span>}
        {status === 'ready' && (
          <>
            <strong>{stats.documents ?? 0}</strong> documents ·{' '}
            <strong>{stats.collection_size ?? 0}</strong> chunks
          </>
        )}
      </p>

      <div
        className={`dropzone ${dragging ? 'is-over' : ''} ${busy ? 'is-busy' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          accept(e.dataTransfer.files)
        }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          className="visually-hidden"
          accept={supported.join(',')}
          onChange={(e) => {
            accept(e.target.files)
            e.target.value = ''
          }}
        />
        <p className="dropzone-line">
          {busy ? 'Parsing and embedding…' : 'Drop files here'}
        </p>
        <button
          type="button"
          className="button-quiet"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
        >
          choose files
        </button>
        {!!supported.length && (
          <p className="dropzone-formats">{supported.join(' · ')}</p>
        )}
      </div>

      {report && (
        <div className={`report ${report.tone}`}>
          <p>{report.message}</p>
          {report.tone === 'error' && (
            <p>
              For anything too large for an upload, or a whole directory:
              <code className="report-cmd">agenticrag-ingest -r ./docs</code>
            </p>
          )}
        </div>
      )}

      {status === 'loading' && (
        <dl className="corpus-facts" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i}>
              <dt>
                <span className="skeleton" style={{ width: '4.5rem' }} />
              </dt>
              <dd>
                <span className="skeleton" style={{ width: '9rem' }} />
              </dd>
            </div>
          ))}
        </dl>
      )}

      {stats?.embedding_model && (
        <dl className="corpus-facts">
          <div>
            <dt>Embeddings</dt>
            <dd>{stats.embedding_model}</dd>
          </div>
          <div>
            <dt>Reranker</dt>
            <dd>{stats.reranker}</dd>
          </div>
          <div>
            <dt>Chunks</dt>
            <dd>
              {stats.chunking?.target_tokens} tokens, {stats.chunking?.overlap_tokens} overlap
            </dd>
          </div>
        </dl>
      )}
    </section>
  )
}
