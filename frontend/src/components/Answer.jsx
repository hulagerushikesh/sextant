import React from 'react'

/**
 * Renders a streamed answer, turning `[3]` into a control that opens passage 3.
 *
 * There is no markdown library here on purpose. The model writes prose with the
 * occasional list or bold phrase, and the one thing the renderer has to get
 * exactly right -- citation labels -- is the one thing a general markdown parser
 * would happily mangle, since `[3]` is also valid link syntax. Sixty lines that
 * handle four constructs and treat `[n]` as a first-class token beat a
 * dependency that handles forty and treats it as a broken link.
 *
 * It also has to survive being fed half a sentence: this runs on every token.
 * An unclosed `**` renders as literal asterisks until its partner arrives, which
 * is the correct behaviour for a stream and needs no special case.
 */

const BULLET = /^\s*[-*•]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/
const HEADING = /^(#{1,4})\s+(.*)$/
// Bold, inline code, or a citation label. Kept in one alternation so the split
// preserves order and nothing is scanned twice.
//
// A label may be a group: models write "[1, 4]" as readily as "[1][4]", and the
// system prompt asks for the latter but does not always get it. Parsing both
// costs one character class and turns a literal "[1, 4]" in the middle of a
// sentence -- which is what shipped first -- into two working controls.
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[\d{1,3}(?:\s*,\s*\d{1,3})*\])/g
const LABEL = /^\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]$/

function Inline({ text, resolve, onCite }) {
  return (
    <>
      {text.split(INLINE).map((part, i) => {
        if (!part) return null
        if (part.startsWith('**') && part.endsWith('**')) {
          return <strong key={i}>{part.slice(2, -2)}</strong>
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return <code key={i}>{part.slice(1, -1)}</code>
        }
        const label = part.match(LABEL)
        if (!label) return <React.Fragment key={i}>{part}</React.Fragment>

        // One chip per number, even when they arrived inside one bracket: each
        // points at a different passage, so each has to be separately clickable.
        return label[1].split(',').map((raw, j) => {
          const n = Number(raw.trim())
          const source = resolve(n)
          if (!source) {
            // A label with nothing behind it. Shown rather than swallowed: this
            // is exactly the failure `eval/judge.py` calls a dangling citation,
            // and it should be as visible in the UI as it is in the metrics.
            return (
              <span
                key={`${i}-${j}`}
                className="cite cite-dangling"
                title="No source carries this label"
              >
                [{n}]
              </span>
            )
          }
          return (
            <button
              key={`${i}-${j}`}
              type="button"
              className={`cite cite-${source.origin}`}
              onClick={() => onCite(n)}
              title={source.title}
            >
              {n}
            </button>
          )
        })
      })}
    </>
  )
}

function Block({ lines, resolve, onCite }) {
  const heading = lines.length === 1 && lines[0].match(HEADING)
  if (heading) {
    const Tag = `h${Math.min(heading[1].length + 2, 6)}`
    return (
      <Tag className="answer-heading">
        <Inline text={heading[2]} resolve={resolve} onCite={onCite} />
      </Tag>
    )
  }

  if (lines.every((line) => BULLET.test(line))) {
    return (
      <ul className="answer-list">
        {lines.map((line, i) => (
          <li key={i}>
            <Inline text={line.replace(BULLET, '')} resolve={resolve} onCite={onCite} />
          </li>
        ))}
      </ul>
    )
  }

  if (lines.every((line) => NUMBERED.test(line))) {
    return (
      <ol className="answer-list">
        {lines.map((line, i) => (
          <li key={i}>
            <Inline text={line.replace(NUMBERED, '')} resolve={resolve} onCite={onCite} />
          </li>
        ))}
      </ol>
    )
  }

  return (
    <p className="answer-para">
      {lines.map((line, i) => (
        <React.Fragment key={i}>
          {i > 0 && <br />}
          <Inline text={line} resolve={resolve} onCite={onCite} />
        </React.Fragment>
      ))}
    </p>
  )
}

export default function Answer({ text, resolve, onCite, streaming }) {
  const blocks = text
    .split(/\n\s*\n/)
    .map((block) => block.split('\n').filter((line) => line.trim()))
    .filter((lines) => lines.length)

  return (
    <div className="answer">
      {blocks.map((lines, i) => (
        <Block key={i} lines={lines} resolve={resolve} onCite={onCite} />
      ))}
      {streaming && <span className="caret" aria-hidden="true" />}
    </div>
  )
}
