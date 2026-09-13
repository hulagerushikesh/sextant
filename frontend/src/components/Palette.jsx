import React, { useEffect, useMemo, useRef, useState } from 'react'

/**
 * The command palette: every action in the app, reachable from the keyboard.
 *
 * ⌘K opens it. There is deliberately no open or close animation -- this is
 * the one control people hit dozens of times a day, and any motion on it
 * reads as lag. It types-ahead over a flat list of commands the app supplies,
 * grouped by kind, with saved conversations mixed in so switching threads is
 * a search rather than a scroll through the rail.
 *
 * Matching is a plain case-insensitive substring over label + keywords, with
 * prefix matches ranked first. Fuzzy scoring would be cleverer and worse: a
 * palette with twenty entries is browsed, not searched.
 */

function rank(commands, query) {
  const q = query.trim().toLowerCase()
  if (!q) return commands
  const scored = []
  for (const command of commands) {
    const hay = `${command.label} ${command.keywords || ''}`.toLowerCase()
    const at = hay.indexOf(q)
    if (at === -1) continue
    scored.push([at === 0 || hay[at - 1] === ' ' ? 0 : 1, at, command])
  }
  return scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((s) => s[2])
}

export default function Palette({ open, commands, onClose }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  const visible = useMemo(() => rank(commands, query), [commands, query])

  // Fresh each time it opens: the last search is never what you want next.
  useEffect(() => {
    if (!open) return
    setQuery('')
    setCursor(0)
    // Focus after paint so the click that opened it does not steal it back.
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [open])

  useEffect(() => setCursor(0), [query])

  useEffect(() => {
    const row = listRef.current?.querySelector('[aria-selected="true"]')
    row?.scrollIntoView({ block: 'nearest' })
  }, [cursor, visible])

  if (!open) return null

  const run = (command) => {
    onClose()
    // Let the palette unmount before the command moves focus elsewhere.
    requestAnimationFrame(() => command.run())
  }

  const onKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((c) => Math.min(c + 1, visible.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((c) => Math.max(c - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (visible[cursor]) run(visible[cursor])
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    }
  }

  // Group headers only where the group changes, so the list reads as sections
  // without a header per row.
  let lastGroup = null

  return (
    <div className="palette-scrim" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Commands"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="palette-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a command or a conversation…"
          aria-label="Search commands"
          aria-controls="palette-list"
          aria-activedescendant={visible[cursor] ? `cmd-${visible[cursor].id}` : undefined}
          autoComplete="off"
          spellCheck={false}
        />
        <ul className="palette-list" id="palette-list" role="listbox" ref={listRef}>
          {visible.length === 0 && (
            <li className="palette-empty">Nothing matches “{query.trim()}”.</li>
          )}
          {visible.map((command, i) => {
            const header = command.group !== lastGroup ? command.group : null
            lastGroup = command.group
            return (
              <React.Fragment key={command.id}>
                {header && (
                  <li className="palette-group" role="presentation">
                    {header}
                  </li>
                )}
                <li
                  id={`cmd-${command.id}`}
                  role="option"
                  aria-selected={i === cursor}
                  className={`palette-item ${i === cursor ? 'is-cursor' : ''}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => run(command)}
                >
                  <span className="palette-label">{command.label}</span>
                  {command.hint && <span className="palette-hint">{command.hint}</span>}
                  {command.keys && (
                    <span className="palette-keys" aria-label={`Shortcut ${command.keys.join(' ')}`}>
                      {command.keys.map((k) => (
                        <kbd key={k}>{k}</kbd>
                      ))}
                    </span>
                  )}
                </li>
              </React.Fragment>
            )
          })}
        </ul>
        <p className="palette-foot">
          <kbd>↑</kbd>
          <kbd>↓</kbd> move · <kbd>↵</kbd> run · <kbd>esc</kbd> close
        </p>
      </div>
    </div>
  )
}
