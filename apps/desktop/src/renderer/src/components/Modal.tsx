import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

const SIZES = { sm: 'max-w-md', md: 'max-w-2xl', lg: 'max-w-3xl' } as const

interface Props {
  title: ReactNode
  description?: ReactNode
  /** Icon shown beside the title, e.g. a warning for destructive confirmations. */
  icon?: ReactNode
  size?: keyof typeof SIZES
  onClose(): void
  /** Bottom bar, usually the action buttons. */
  footer?: ReactNode
  children?: ReactNode
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * The frame every dialog uses: dimmed backdrop, panel, header with a close button, scrolling body
 * and a footer. Escape or a click on the backdrop closes it. Keyboard focus moves into the dialog,
 * stays there while it's open (Tab wraps), and returns to where it was when it closes. Key presses
 * don't reach the window, so editor shortcuts (Delete, Space…) can't fire behind an open dialog.
 */
export function Modal({ title, description, icon, size = 'md', onClose, footer, children }: Props) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  // Read through a ref so a parent re-render with a new onClose doesn't re-run the focus effect.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    // Autofocus whatever is marked data-autofocus, else the first control in the body or footer.
    // Never the header's Close button: Enter or Space would dismiss the dialog straight away.
    const target =
      panel?.querySelector<HTMLElement>('[data-autofocus]') ??
      [...(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])].find((el) => !el.hasAttribute('data-modal-close'))
    ;(target ?? panel)?.focus()
    return () => previous?.focus?.()
  }, [])

  const onKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation()
    if (e.key === 'Escape') {
      e.preventDefault()
      onCloseRef.current()
    } else if (e.key === 'Tab' && panelRef.current) {
      const items = [...panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[var(--ui-overlay)] p-6" onMouseDown={() => onCloseRef.current()}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className={`flex max-h-full w-full ${SIZES[size]} flex-col overflow-hidden rounded-2xl border border-line bg-dialog shadow-dialog outline-none glass-float`}
      >
        <div className="flex items-center gap-3 border-b border-line bg-white/5 px-5 py-4">
          {icon && <div className="shrink-0">{icon}</div>}
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-lg font-semibold">
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className="mt-0.5 text-xs text-muted">
                {description}
              </p>
            )}
          </div>
          <button
            data-modal-close
            onClick={() => onCloseRef.current()}
            aria-label="Close"
            className="-mr-1.5 grid size-8 shrink-0 place-items-center rounded-full bg-white/8 text-muted hover:bg-white/15 hover:text-ink"
          >
            <X size={16} />
          </button>
        </div>
        {children}
        {footer && <div className="flex items-center justify-between gap-3 border-t border-dashed border-white/15 px-5 py-3">{footer}</div>}
      </div>
    </div>
  )
}
