import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import ts from 'typescript'
import { root } from './paths.mjs'

const source = readFileSync(join(root, 'apps', 'desktop', 'src', 'renderer', 'src', 'lib', 'audio.ts'), 'utf8')
const javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
}).outputText
const module = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`)

const clip = { level: 150, muted: false }
assert.equal(module.clipExportGain(clip), 1.5)
assert.equal(module.previewGain(100, false, clip), 1.5)
assert.equal(module.previewGain(50, false, clip), 0.75)
assert.equal(module.previewGain(50, true, clip), 0)
assert.equal(module.clipExportGain(clip), 1.5, 'monitor mute must not affect export gain')
assert.equal(module.clipExportGain({ level: 150, muted: true }), 0)
console.log('audio controls: monitoring and clip output gains are independent')
