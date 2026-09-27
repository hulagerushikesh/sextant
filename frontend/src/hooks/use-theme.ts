import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark' | 'system'

const KEY = 'theme'

function systemDark() {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem(KEY) as Theme) || 'system')

  useEffect(() => {
    const root = document.documentElement
    const apply = () => root.classList.toggle('dark', theme === 'dark' || (theme === 'system' && systemDark()))
    apply()
    localStorage.setItem(KEY, theme)
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [theme])

  const resolved: 'light' | 'dark' = theme === 'system' ? (systemDark() ? 'dark' : 'light') : theme
  const toggle = useCallback(() => setTheme(resolved === 'dark' ? 'light' : 'dark'), [resolved])
  return { theme, resolved, setTheme, toggle }
}
