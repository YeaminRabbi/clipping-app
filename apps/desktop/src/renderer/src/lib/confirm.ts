import type { ReactNode } from 'react'
import { create } from 'zustand'

export interface ConfirmOptions {
  title: string
  message?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** Red confirm button and a warning icon, for actions that delete things. */
  danger?: boolean
}

interface Pending extends ConfirmOptions {
  resolve(ok: boolean): void
}

/** The open question, rendered by ConfirmDialogHost (components/ConfirmDialog.tsx). */
export const useConfirmStore = create<{ pending: Pending | null }>(() => ({ pending: null }))

/**
 * Ask the user to confirm, in the app's own dialog instead of the browser's confirm().
 * Resolves to true if they confirm, false if they cancel or close it.
 */
export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    // A newer question replaces an unanswered one, which counts as cancelled.
    useConfirmStore.getState().pending?.resolve(false)
    useConfirmStore.setState({ pending: { ...options, resolve } })
  })
}
