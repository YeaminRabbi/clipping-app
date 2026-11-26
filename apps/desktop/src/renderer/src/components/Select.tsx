import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'

export interface SelectOption<T extends string | number> {
  value: T
  label: string
  /** Optional style for the option's text (e.g. a font preview). */
  style?: CSSProperties
}

interface Props<T extends string | number> {
  value: T
  options: SelectOption<T>[]
  onChange(value: T): void
  /** Classes for the closed control; the list itself always uses the app's glass style. */
  className?: string
  id?: string
  title?: string
  'aria-label'?: string
  disabled?: boolean
}

const MAX_LIST_HEIGHT = 288

/**
 * A dropdown drawn by the app instead of Windows, so the open list matches the glass theme.
 * Works with the keyboard like a native one: arrows, Home/End, Enter or Space to pick, Escape to close,
 * and typing a letter jumps to the next option starting with it.
 */
export function Select<T extends string | number>({ value, options, onChange, className, id, title, disabled, ...rest }: Props<T>) {
  const listId = useId()
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [place, setPlace] = useState<{ left: number; width: number; top?: number; bottom?: number; maxHeight: number } | null>(null)

  const selectedIndex = Math.max(0, options.findIndex((o) => o.value === value))
  const selected = options[selectedIndex]

  const position = () => {
    const rect = buttonRef.current?.getBoundingClientRect()
    if (!rect) return
    const below = window.innerHeight - rect.bottom - 12
    const above = rect.top - 12
    const width = Math.max(rect.width, 180)
    const left = Math.min(rect.left, window.innerWidth - width - 8)
    // Opens downwards unless there's clearly more room above.
    if (below >= Math.min(MAX_LIST_HEIGHT, 160) || below >= above) {
      setPlace({ left, width, top: rect.bottom + 6, maxHeight: Math.min(MAX_LIST_HEIGHT, below) })
    } else {
      setPlace({ left, width, bottom: window.innerHeight - rect.top + 6, maxHeight: Math.min(MAX_LIST_HEIGHT, above) })
    }
  }

  const openList = () => {
    if (disabled) return
    position()
    setActive(selectedIndex)
    setOpen(true)
  }

  const close = (refocus = true) => {
    setOpen(false)
    if (refocus) buttonRef.current?.focus()
  }

  const pick = (index: number) => {
    const option = options[index]
    if (option && option.value !== value) onChange(option.value)
    close()
  }

  // Closes on a click outside, and when the page scrolls or resizes under it.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (!listRef.current?.contains(target) && !buttonRef.current?.contains(target)) close(false)
    }
    const onMove = (e: Event) => {
      if (!listRef.current?.contains(e.target as Node)) close(false)
    }
    document.addEventListener('mousedown', onDown, true)
    window.addEventListener('resize', onMove)
    window.addEventListener('scroll', onMove, true)
    return () => {
      document.removeEventListener('mousedown', onDown, true)
      window.removeEventListener('resize', onMove)
      window.removeEventListener('scroll', onMove, true)
    }
  }, [open])

  // Keeps the highlighted option in view.
  useLayoutEffect(() => {
    if (!open) return
    const item = listRef.current?.children[active] as HTMLElement | undefined
    item?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  const onKeyDown = (e: KeyboardEvent) => {
    if (disabled) return
    const last = options.length - 1
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
        e.preventDefault()
        openList()
      }
      return
    }
    switch (e.key) {
      case 'ArrowDown':
        setActive((a) => Math.min(last, a + 1))
        break
      case 'ArrowUp':
        setActive((a) => Math.max(0, a - 1))
        break
      case 'Home':
        setActive(0)
        break
      case 'End':
        setActive(last)
        break
      case 'Enter':
      case ' ':
        pick(active)
        break
      case 'Escape':
        close()
        break
      case 'Tab':
        close(false)
        return
      default:
        if (e.key.length === 1) {
          const letter = e.key.toLowerCase()
          const order = [...options.keys()].map((i) => (active + 1 + i) % options.length)
          const next = order.find((i) => options[i].label.toLowerCase().startsWith(letter))
          if (next !== undefined) setActive(next)
        }
        return
    }
    e.preventDefault()
    // Escape here closes only the list, not a dialog around it.
    e.stopPropagation()
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        id={id}
        title={title}
        disabled={disabled}
        aria-label={rest['aria-label']}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => (open ? close() : openList())}
        onKeyDown={onKeyDown}
        className={`flex items-center justify-between gap-2 text-left disabled:opacity-50 ${className ?? ''}`}
      >
        <span className="min-w-0 truncate" style={selected?.style}>
          {selected?.label ?? ''}
        </span>
        <ChevronDown size={14} aria-hidden className={`shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open &&
        place &&
        createPortal(
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            aria-activedescendant={`${listId}-${active}`}
            tabIndex={-1}
            onMouseDown={(e) => e.preventDefault()}
            style={{ left: place.left, width: place.width, top: place.top, bottom: place.bottom, maxHeight: place.maxHeight }}
            className="glass-float fixed z-[60] overflow-y-auto rounded-2xl border bg-[rgba(24,36,60,0.82)] p-1.5 text-sm text-ink shadow-dialog"
          >
            {options.map((option, i) => {
              const isSelected = i === selectedIndex
              return (
                <li
                  key={String(option.value)}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={isSelected}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => pick(i)}
                  className={`flex cursor-pointer items-center justify-between gap-3 rounded-xl px-3 py-2 ${
                    i === active ? 'bg-white/12' : ''
                  } ${isSelected ? 'font-semibold' : ''}`}
                >
                  <span className="min-w-0 truncate" style={option.style}>
                    {option.label}
                  </span>
                  {isSelected && <Check size={14} strokeWidth={2.5} aria-hidden className="shrink-0" />}
                </li>
              )
            })}
          </ul>,
          document.body
        )}
    </>
  )
}
