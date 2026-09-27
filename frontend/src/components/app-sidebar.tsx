import { FlaskConical, MessageSquare, Plus, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { money, totals } from '@/lib/store'
import type { Conversation } from '@/lib/types'
import { Button } from '@/components/ui/button'
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader,
  SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem, SidebarRail,
} from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

export type View = 'chat' | 'lab'

interface Props {
  view: View
  onView: (v: View) => void
  conversations: Conversation[]
  activeId: string
  onOpen: (c: Conversation) => void
  onNew: () => void
  onDelete: (id: string) => void
  health: 'ok' | 'degraded' | 'down' | null
}

export function AppSidebar({ view, onView, conversations, activeId, onOpen, onNew, onDelete, health }: Props) {
  const threads = conversations.filter((c) => c.messages.length)
  return (
    <Sidebar collapsible="offcanvas" className="border-r">
      <SidebarHeader className="px-3 pt-3.5 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 px-1">
            <Mark />
            <div className="leading-none">
              <div className="text-[13px] font-semibold tracking-tight">Sextant</div>
              <div className="mt-0.5 text-[10.5px] text-muted-foreground">Agentic RAG over MCP</div>
            </div>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={onNew} aria-label="New conversation"><Plus /></Button>
            </TooltipTrigger>
            <TooltipContent>New conversation <span className="ml-1 font-mono text-[10px] opacity-70">⌥N</span></TooltipContent>
          </Tooltip>
        </div>
      </SidebarHeader>

      <SidebarContent className="scrollbar-thin">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton isActive={view === 'chat'} onClick={() => onView('chat')}>
                  <MessageSquare /> <span>Chat</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton isActive={view === 'lab'} onClick={() => onView('lab')}>
                  <FlaskConical /> <span>Index Lab</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Conversations</SidebarGroupLabel>
          <SidebarGroupContent>
            {threads.length ? (
              <SidebarMenu>
                {threads.map((c) => {
                  const active = c.id === activeId && view === 'chat'
                  return (
                    <SidebarMenuItem key={c.id} className="group/thread">
                      <SidebarMenuButton isActive={active} onClick={() => onOpen(c)} className="h-8 pr-7" title={c.title}>
                        <span className={cn('size-1.5 shrink-0 rounded-full', active ? 'bg-corpus' : 'bg-transparent')} />
                        <span className="truncate">{c.title}</span>
                        <span className="ml-auto font-mono text-[10px] text-muted-foreground tabular group-hover/thread:hidden">{money(totals(c.messages).costUsd)}</span>
                      </SidebarMenuButton>
                      <SidebarMenuAction showOnHover onClick={() => onDelete(c.id)} aria-label={`Delete ${c.title}`} className="hover:text-destructive">
                        <Trash2 />
                      </SidebarMenuAction>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            ) : (
              <p className="px-2 py-1 text-[12px] leading-snug text-muted-foreground">Conversations you have are kept in this browser.</p>
            )}
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="px-3 pb-3">
        <div className="flex items-center gap-2 px-1 text-[11px] text-muted-foreground">
          <span className={cn('size-1.5 rounded-full', health === 'ok' ? 'bg-success' : health === 'degraded' ? 'bg-warning' : health === 'down' ? 'bg-destructive' : 'bg-muted-foreground/40')} />
          {health === 'ok' ? 'Server healthy' : health === 'degraded' ? 'Degraded — no model key' : health === 'down' ? 'Server unreachable' : 'Checking…'}
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

/** A sextant's index arm — the one graphic in the app. */
function Mark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true" className="shrink-0">
      <path d="M13 3.5 A 9.5 9.5 0 0 1 22.5 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="text-muted-foreground" />
      <path d="M13 3.5 A 9.5 9.5 0 0 0 3.5 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="text-muted-foreground/40" />
      <path d="M13 13 L 20.2 6.8" stroke="var(--corpus)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="13" cy="13" r="2" fill="var(--corpus)" />
      <path d="M4 22.5 H 22" stroke="var(--web)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}
