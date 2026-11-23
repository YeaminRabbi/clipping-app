import type { ClippingBridge } from '../shared/types'

declare global {
  interface Window {
    clipping: ClippingBridge
  }
}

export {}
