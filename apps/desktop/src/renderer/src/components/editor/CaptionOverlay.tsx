import type { CSSProperties } from 'react'
import type { CaptionCue, CaptionStyle } from '../../lib/api'

const REFERENCE_HEIGHT = 1920

/** CSS approximation of how a caption style renders, for previews. Sizes scale with `frameH`. */
export function captionTextStyle(style: CaptionStyle, frameH: number): CSSProperties {
  const scale = frameH / REFERENCE_HEIGHT
  const css: CSSProperties = {
    fontFamily: `"${style.font}", "Arial Black", sans-serif`,
    fontWeight: style.bold ? 900 : 500,
    fontSize: style.size * scale,
    lineHeight: 1.15,
    color: style.color,
    textTransform: style.uppercase ? 'uppercase' : 'none'
  }
  if (style.box) {
    css.background = 'rgba(0, 0, 0, 0.62)'
    css.padding = `${4 * scale * 3}px ${10 * scale * 3}px`
    css.borderRadius = 4 * scale * 3
    css.boxDecorationBreak = 'clone'
    css.WebkitBoxDecorationBreak = 'clone'
  } else if (style.outline > 0) {
    css.WebkitTextStroke = `${style.outline * 2 * scale}px #000`
    css.paintOrder = 'stroke fill'
    css.textShadow = `0 ${2 * scale}px ${4 * scale}px rgba(0,0,0,0.5)`
  }
  return css
}

function placement(style: CaptionStyle): CSSProperties {
  const base: CSSProperties = { left: '8%', right: '8%', textAlign: 'center' }
  if (style.position === 'top') return { ...base, top: '10%' }
  if (style.position === 'middle') return { ...base, top: '50%', transform: 'translateY(-50%)' }
  return { ...base, bottom: '12%' }
}

/** Renders the caption cue active at `timeMs` over the output preview. */
export function CaptionOverlay({ cues, style, timeMs, frameH }: { cues: CaptionCue[]; style: CaptionStyle; timeMs: number; frameH: number }) {
  const cue = cues.find((c) => timeMs >= c.start && timeMs < c.end)
  if (!cue) return null
  const active = cue.words.findLastIndex((w) => w.start <= timeMs)
  return (
    <div className="pointer-events-none absolute" style={placement(style)}>
      <span style={captionTextStyle(style, frameH)}>
        {cue.words.map((w, i) => {
          const highlighted =
            style.highlight && ((style.effect === 'pop' && i === Math.max(active, 0)) || (style.effect === 'karaoke' && i <= active))
          return (
            <span key={w.index}>
              {i > 0 && ' '}
              <span
                style={
                  highlighted
                    ? { color: style.highlight, display: 'inline-block', transform: style.effect === 'pop' ? 'scale(1.1)' : undefined }
                    : undefined
                }
              >
                {w.text}
              </span>
            </span>
          )
        })}
      </span>
    </div>
  )
}
