import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { ArrowUp, Globe, Square } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MOD } from '@/lib/store'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/**
 * Grow the composer with its content, one line to six. A fixed two-row box
 * wasted a line on every short question and still clipped a long one;
 * measuring scrollHeight after resetting the height is the whole trick.
 */
const MAX_HEIGHT = 160

function autosize(box: HTMLTextAreaElement) {
  box.style.height = 'auto'
  box.style.height = `${Math.min(box.scrollHeight, MAX_HEIGHT)}px`
}

interface Props {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  onStop: () => void
  streaming: boolean
  webSearch: boolean
  onToggleWeb: () => void
  hasMessages: boolean
}

export const Composer = forwardRef<HTMLTextAreaElement, Props>(function Composer(
  { value, onChange, onSubmit, onStop, streaming, webSearch, onToggleWeb, hasMessages }, ref,
) {
  const boxRef = useRef<HTMLTextAreaElement>(null)
  useImperativeHandle(ref, () => boxRef.current as HTMLTextAreaElement, [])

  // Runs on every draft change, which also covers the two paths that set the
  // draft from outside the box: a starter click and the post-send reset.
  useEffect(() => {
    if (boxRef.current) autosize(boxRef.current)
  }, [value])

  return (
    <div className="mx-auto w-full max-w-[72ch]">
      <form
        onSubmit={(e) => { e.preventDefault(); onSubmit() }}
        className={cn(
          'group/composer relative rounded-xl border bg-card shadow-sm transition-[box-shadow,border-color] duration-200',
          'focus-within:border-ring/60 focus-within:shadow-md',
          webSearch && 'border-web/50',
        )}
      >
        <textarea
          ref={boxRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSubmit() } }}
          placeholder={hasMessages ? 'Ask a follow-up…' : 'Ask a question about your documents…'}
          rows={1}
          maxLength={2000}
          aria-label="Your question"
          style={{ maxHeight: MAX_HEIGHT }}
          className="block w-full resize-none overflow-y-auto bg-transparent px-4 pt-3.5 pb-2 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground/70"
        />
        <div className="flex items-center justify-between gap-2 px-2.5 pb-2.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant={webSearch ? 'secondary' : 'ghost'}
                size="sm"
                aria-pressed={webSearch}
                onClick={onToggleWeb}
                disabled={streaming}
                className={cn('gap-1.5 text-muted-foreground', webSearch && 'bg-web-muted text-web hover:bg-web-muted')}
              >
                <Globe className={cn('size-3.5', webSearch && 'text-web')} />
                Web {webSearch ? 'on' : 'off'}
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-[26ch]">
              Google Search is billed per request (~$0.014). Off by default; turns on for this one question.
            </TooltipContent>
          </Tooltip>

          {streaming ? (
            <Button type="button" size="sm" variant="outline" onClick={onStop} className="gap-1.5">
              <Square className="size-3 fill-current" /> Stop <Kbd>esc</Kbd>
            </Button>
          ) : (
            <Button type="submit" size="icon-sm" disabled={!value.trim()} aria-label="Ask" className="rounded-lg">
              <ArrowUp />
            </Button>
          )}
        </div>
      </form>
      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[11.5px] text-muted-foreground">
        <span><Kbd>↵</Kbd> send</span>
        <span><Kbd>⇧↵</Kbd> new line</span>
        <span><Kbd>/</Kbd> focus</span>
        <span><Kbd>{MOD}K</Kbd> commands</span>
        {webSearch && !streaming && <span className="text-web">· web search on for this question, about $0.014</span>}
      </p>
    </div>
  )
})
