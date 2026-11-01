import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

// Record renderer crashes in the app log so they can be diagnosed later.
window.addEventListener('error', (e) => window.clipping.app.reportError(`${e.message} at ${e.filename}:${e.lineno}`))
window.addEventListener('unhandledrejection', (e) => window.clipping.app.reportError(`Unhandled rejection: ${String(e.reason)}`))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
