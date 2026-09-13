import React, { useCallback, useEffect, useRef, useState } from 'react'

/**
 * One transient confirmation at a time, bottom-centre.
 *
 * Kept deliberately small: the app has a handful of actions that deserve a
 * "that happened" -- copied, deleted, theme switched from the palette -- and
 * a toast stack would be more machinery than there are messages. A new toast
 * replaces the current one and restarts the clock. It slides in from where it
 * leaves to, so the motion reads as one object rather than two.
 */

export function useToast(ms = 2200) {
  const [toast, setToast] = useState(null)
  const timer = useRef(null)

  const show = useCallback(
    (text) => {
      clearTimeout(timer.current)
      setToast({ text, key: Date.now() })
      timer.current = setTimeout(() => setToast(null), ms)
    },
    [ms]
  )

  useEffect(() => () => clearTimeout(timer.current), [])
  return [toast, show]
}

export default function Toast({ toast }) {
  const [mounted, setMounted] = useState(false)

  // Enter on the frame after mount so the transition has a "from" to leave.
  useEffect(() => {
    if (!toast) {
      setMounted(false)
      return undefined
    }
    const id = requestAnimationFrame(() => setMounted(true))
    return () => cancelAnimationFrame(id)
  }, [toast])

  if (!toast) return null
  return (
    <div className="toast" data-mounted={mounted} role="status" aria-live="polite" key={toast.key}>
      {toast.text}
    </div>
  )
}
