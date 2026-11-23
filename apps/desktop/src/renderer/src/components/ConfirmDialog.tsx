import { TriangleAlert } from 'lucide-react'
import { useConfirmStore } from '../lib/confirm'
import { Modal } from './Modal'

/** Renders the open confirmation, if any. Mounted once, in App. */
export function ConfirmDialogHost() {
  const pending = useConfirmStore((s) => s.pending)
  if (!pending) return null

  const answer = (ok: boolean): void => {
    useConfirmStore.setState({ pending: null })
    pending.resolve(ok)
  }

  return (
    <Modal
      size="sm"
      title={pending.title}
      icon={
        pending.danger ? (
          <div className="grid size-8 place-items-center rounded-full bg-danger-subtle text-danger">
            {/* A triangle's weight sits in its base, so geometric centring looks low; lift it 1px. */}
            <TriangleAlert size={16} aria-hidden className="-translate-y-px" />
          </div>
        ) : undefined
      }
      onClose={() => answer(false)}
      footer={
        <div className="ml-auto flex gap-2">
          {/* Destructive actions start focused on Cancel, so a stray Enter deletes nothing. */}
          <button data-autofocus={pending.danger || undefined} onClick={() => answer(false)} className="rounded-md px-4 py-2 text-sm text-muted hover:bg-panel-2 hover:text-ink">
            {pending.cancelLabel ?? 'Cancel'}
          </button>
          <button
            data-autofocus={!pending.danger || undefined}
            onClick={() => answer(true)}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white ${
              pending.danger ? 'bg-red-600 hover:bg-red-700' : 'bg-accent hover:bg-accent-hover'
            }`}
          >
            {pending.confirmLabel ?? 'Confirm'}
          </button>
        </div>
      }
    >
      {pending.message && <div className="px-5 py-4 text-sm text-muted">{pending.message}</div>}
    </Modal>
  )
}
