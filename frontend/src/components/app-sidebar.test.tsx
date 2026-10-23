/**
 * The footer is the only place the app says what is wrong with the server.
 * It used to say "Degraded — no model key" whenever anything was wrong,
 * including when the model key was fine and the knowledge base was the thing
 * that had not started.
 */
import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'
import { AppSidebar } from './app-sidebar'
import { SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { healthLine } from '@/lib/health'
import type { HealthLine } from '@/lib/health'
import type { Health } from '@/lib/types'

beforeAll(() => {
  // jsdom has no matchMedia, and `useIsMobile` calls it on mount.
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

const health = (over: Partial<Health>): Health => ({
  status: 'degraded',
  mcp_connected: true,
  model_configured: true,
  supported_uploads: ['.md'],
  web_search_enabled: false,
  budget: { enabled: false } as Health['budget'],
  mcp_error: null,
  tools_discovered: [],
  tools_offered_to_model: [],
  ...over,
})

const show = (line: HealthLine | null) =>
  render(
    <TooltipProvider>
      <SidebarProvider>
        <AppSidebar
          view="chat" onView={() => {}} conversations={[]} activeId="c1"
          onOpen={() => {}} onNew={() => {}} onDelete={() => {}} health={line}
        />
      </SidebarProvider>
    </TooltipProvider>,
  )

describe('the footer names the fault it was told about', () => {
  it('does not report a missing key when the knowledge base is what is down', () => {
    show(healthLine({ reached: true, health: health({ mcp_connected: false }) }))
    expect(screen.queryByText(/no model key/i)).toBeNull()
    expect(screen.getByText(/knowledge base not connected/i)).toBeTruthy()
  })

  it('reports a missing key when that is the fault', () => {
    show(healthLine({ reached: true, health: health({ model_configured: false }) }))
    expect(screen.getByText(/no model key/i)).toBeTruthy()
  })

  it('puts the server own error where a reader can get at it', () => {
    show(healthLine({ reached: true, health: health({ mcp_connected: false, mcp_error: 'spawn python ENOENT' }) }))
    expect(screen.getByTitle('spawn python ENOENT')).toBeTruthy()
  })

  it('says it is still checking before the first answer comes back', () => {
    show(null)
    expect(screen.getByText('Checking…')).toBeTruthy()
  })
})
