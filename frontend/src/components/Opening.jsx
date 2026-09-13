import React from 'react'

/**
 * What an empty thread shows.
 *
 * Three states, decided by what the corpus actually contains rather than by
 * a generic welcome: still finding out (skeleton), nothing indexed yet (the
 * only useful next step is adding documents, so that is the whole screen),
 * and a corpus that can be asked about (starters that send on click).
 *
 * The first-run card sits above all three until dismissed. It says the three
 * things that are not obvious from looking at the interface: where documents
 * come from, that the corpus is searched before the web, and that ⌘K exists.
 */

const STARTERS = [
  'What topics do my documents cover?',
  'Give me a one-paragraph overview of the corpus.',
  'What is the single most important idea in these documents?',
]

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
export const MOD = isMac ? '⌘' : 'Ctrl'

export default function Opening({ corpus, recent, onAsk, onAddFiles, firstRun, onDismissFirstRun }) {
  const loading = corpus.status === 'loading'
  const empty = corpus.status === 'ready' && !(corpus.stats?.documents > 0)
  const unreachable = corpus.status === 'failed'
  // A starter the user already asked belongs in "pick up", not twice.
  const fresh = STARTERS.filter((q) => !recent.includes(q))

  return (
    <div className="opening">
      {firstRun && (
        <section className="firstrun" aria-label="Getting started">
          <ol className="firstrun-steps">
            <li>
              <strong>Add documents.</strong> Drop files on the Corpus panel, or index a folder
              with <code>agenticrag-ingest -r ./docs</code>. PDFs keep their page numbers.
            </li>
            <li>
              <strong>Ask.</strong> The agent searches your corpus first and only reaches for
              the web when you switch it on for a question.
            </li>
            <li>
              <strong>Check its work.</strong> Every claim carries a numbered passage. Click a{' '}
              <span className="cite-example">[1]</span> to read what it came from.
            </li>
          </ol>
          <div className="firstrun-foot">
            <span>
              <kbd>{MOD}</kbd>
              <kbd>K</kbd> opens every command
            </span>
            <button type="button" className="button-quiet" onClick={onDismissFirstRun}>
              Got it
            </button>
          </div>
        </section>
      )}

      {loading && (
        <div aria-busy="true" aria-label="Checking the corpus">
          <span className="skeleton" style={{ width: '60%', height: '1.6rem', marginBottom: 14 }} />
          <span className="skeleton" style={{ width: '90%', marginBottom: 8 }} />
          <span className="skeleton" style={{ width: '75%' }} />
        </div>
      )}

      {unreachable && (
        <>
          <h2>The knowledge base is not answering.</h2>
          <p>
            The server is up but its retrieval subprocess is not. Check the server log — the
            usual cause is a model still downloading on first start.
          </p>
        </>
      )}

      {empty && (
        <>
          <h2>Nothing to search yet.</h2>
          <p>
            Questions run against your own documents, and there are none indexed. Add some
            and the agent can start citing them.
          </p>
          <div className="opening-actions">
            <button type="button" className="button" onClick={onAddFiles}>
              Add documents
            </button>
            <span className="opening-or">
              or run <code>agenticrag-ingest -r ./docs</code>
            </span>
          </div>
        </>
      )}

      {corpus.status === 'ready' && !empty && (
        <>
          <h2>Ask something your documents can answer.</h2>
          <p>
            <strong>{corpus.stats.documents.toLocaleString()}</strong> documents,{' '}
            <strong>{corpus.stats.collection_size.toLocaleString()}</strong> passages indexed.
            An empty answer is a real answer here — retrieval that finds nothing is reported as
            nothing found, not filled in from memory.
          </p>

          {recent.length > 0 && (
            <div className="starters">
              <h3 className="starters-heading">Pick up where you left off</h3>
              <ul className="starter-list">
                {recent.map((question) => (
                  <li key={question}>
                    <button type="button" className="starter" onClick={() => onAsk(question)}>
                      {question}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {fresh.length > 0 && (
          <div className="starters">
            <h3 className="starters-heading">{recent.length ? 'Or start fresh' : 'Try one of these'}</h3>
            <ul className="starter-list">
              {fresh.map((question) => (
                <li key={question}>
                  <button type="button" className="starter" onClick={() => onAsk(question)}>
                    {question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          )}
        </>
      )}
    </div>
  )
}
