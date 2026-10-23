import { MOCK, MOCK_NOTICE } from '@/lib/api'
import { Badge } from '@/components/ui/badge'

/**
 * The one thing on screen saying that nothing on screen is real.
 *
 * It used to be `<Badge className="hidden ... sm:inline-flex">mock</Badge>` in
 * the header, which is to say: absent below 640px. A phone got the invented
 * answers, the invented spend against the daily cap, the invented recall
 * curves and the toast claiming a document was indexed, with no mark at all --
 * on the screen with the least room for a reader to notice from context. The
 * only warning in the app was the only element hidden at the narrow
 * breakpoint.
 *
 * So: never breakpoint-hidden, warning-coloured rather than muted, and the
 * sentence itself available to a screen reader and on hover instead of the
 * word "mock", which reads as a label and not as a warning.
 */
export function MockNotice() {
  if (!MOCK) return null
  return (
    <Badge
      variant="outline"
      role="status"
      title={MOCK_NOTICE}
      // `shrink-0` so the conversation title beside it truncates first. The
      // notice is the thing that may not be given up for space.
      className="ml-1 shrink-0 border-warning/40 bg-warning-muted font-mono text-[10px] text-warning"
    >
      <span aria-hidden="true">mock data</span>
      <span className="sr-only">{MOCK_NOTICE}</span>
    </Badge>
  )
}
