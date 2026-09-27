import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandShortcut } from '@/components/ui/command'
import { Kbd } from '@/components/ui/kbd'

export interface CommandSpec {
  id: string
  group: string
  label: string
  hint?: string
  keys?: string[]
  keywords?: string
  run: () => void
}

/** ⌘K. Every action in the app, typed-ahead. Conditional entries are left out, not greyed. */
export function CommandPalette({ open, onOpenChange, commands }: { open: boolean; onOpenChange: (o: boolean) => void; commands: CommandSpec[] }) {
  const groups = commands.reduce<Record<string, CommandSpec[]>>((acc, c) => {
    ;(acc[c.group] ||= []).push(c)
    return acc
  }, {})
  const run = (c: CommandSpec) => {
    onOpenChange(false)
    requestAnimationFrame(() => c.run())
  }
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Commands" description="Type a command or a conversation" className="max-w-xl">
      <Command loop>
        <CommandInput placeholder="Type a command or a conversation…" />
        <CommandList className="max-h-[50vh]">
          <CommandEmpty>Nothing matches.</CommandEmpty>
          {Object.entries(groups).map(([group, items]) => (
            <CommandGroup key={group} heading={group}>
              {items.map((c) => (
                <CommandItem key={c.id} value={`${c.label} ${c.keywords || ''}`} onSelect={() => run(c)}>
                  <span className="truncate">{c.label}</span>
                  {c.hint && <span className="ml-2 truncate font-mono text-[11px] text-muted-foreground">{c.hint}</span>}
                  {c.keys && (
                    <CommandShortcut className="flex gap-1 tracking-normal">
                      {c.keys.map((k) => <Kbd key={k}>{k}</Kbd>)}
                    </CommandShortcut>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
        <div className="flex items-center gap-3 border-t px-3 py-2 text-[11px] text-muted-foreground">
          <span><Kbd>↑</Kbd><Kbd>↓</Kbd> move</span>
          <span><Kbd>↵</Kbd> run</span>
          <span><Kbd>esc</Kbd> close</span>
        </div>
      </Command>
    </CommandDialog>
  )
}
