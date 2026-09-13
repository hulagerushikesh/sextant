import React from 'react'

/**
 * The numbered source list for the whole conversation.
 *
 * Numbers are conversation-scoped, not per-answer: the fifth question can cite
 * [2] from the first, and clicking that label in either answer opens the same
 * card. Restoring those labels across a stateless server is what
 * `SourceRegistry.restore` exists for.
 */

const ORIGIN = { knowledge_base: 'Corpus', web: 'Web' }

// Google hands back a redirect through its own domain rather than the page's
// address, and requires that link be the one shown. The site name is the only
// human-readable part, so it is what the card leads with.
const displayHost = (url) => {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

export default function SourcePanel({ sources, active, onSelect }) {
  if (!sources.length) {
    return (
      <p className="rail-empty">
        Sources appear here as the agent retrieves them, numbered the way the
        answer cites them.
      </p>
    )
  }

  return (
    <ol className="sources">
      {sources.map((source) => {
        const isActive = active === source.n
        return (
          <li
            key={source.n}
            id={`source-${source.n}`}
            className={`source ${isActive ? 'is-active' : ''}`}
          >
            <button
              type="button"
              className="source-head"
              onClick={() => onSelect(isActive ? null : source.n)}
              aria-expanded={isActive}
            >
              <span className={`source-n ${source.origin}`}>{source.n}</span>
              <span className="source-title">{source.title}</span>
              <span className={`source-origin ${source.origin}`}>
                {ORIGIN[source.origin] || source.origin}
              </span>
            </button>

            <div className="source-meta">
              {source.location && <span className="source-loc">{source.location}</span>}
              {source.score != null && (
                <span className="source-score" title="Cross-encoder relevance, 0-1">
                  {Number(source.score).toFixed(2)}
                </span>
              )}
            </div>

            {isActive && (
              <div className="source-body">
                {source.text ? (
                  <p className="source-text">{source.text}</p>
                ) : (
                  // Web results carry no snippet: Google's grounding metadata
                  // names the site and gives a link, and keeps the passage the
                  // model read to itself. A source restored from an earlier turn
                  // is empty for a different reason -- only the label travelled
                  // between questions, not the passage.
                  <p className="source-text is-absent">
                    {source.origin === 'web'
                      ? 'Google returns the site and a link, not the text the model read. Follow the link to see the page.'
                      : 'Retrieved in an earlier turn. Ask again to pull the passage back.'}
                  </p>
                )}
                {source.url && (
                  <a className="source-link" href={source.url} target="_blank" rel="noreferrer">
                    {source.title || displayHost(source.url)}
                  </a>
                )}
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
