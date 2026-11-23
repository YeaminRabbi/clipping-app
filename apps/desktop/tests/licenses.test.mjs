import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { ffmpegNotice, notices } from '../../../scripts/collect-licenses.mjs'

const describe = (configuration) => () => ({ version: '9.1', configuration })

function withDir(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'licenses-'))
  try {
    fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

test('packaging stops when FFmpeg has no license text', () => {
  withDir((dir) => assert.throws(() => ffmpegNotice(dir, describe('--enable-gpl')), /FFMPEG-LICENSE\.txt is missing/))
})

test('the notice names the license the build was made under, and the source', () => {
  withDir((dir) => {
    writeFileSync(join(dir, 'FFMPEG-LICENSE.txt'), 'x')
    assert.match(ffmpegNotice(dir, describe('--enable-gpl --enable-libx264')), /GNU General Public License[\s\S]*Source code/)
    assert.match(ffmpegNotice(dir, describe('--disable-gpl')), /GNU Lesser General/)
    assert.throws(() => ffmpegNotice(dir, describe('--enable-nonfree')), /may not be distributed/)
  })
})

test('every package is listed, with its license text when it has one', () => {
  withDir((dir) => {
    const file = join(dir, 'LICENSE')
    writeFileSync(file, 'Permission is hereby granted')
    const text = notices('T', [
      { name: 'b', version: '2', license: '', home: '', files: [] },
      { name: 'a', version: '1', license: 'MIT', home: 'h', files: [file] }
    ])
    assert.match(text, /a 1 \(MIT\) h\nPermission[\s\S]*b 2 \(license not stated\)[\s\S]*no license file/)
  })
})

test('the installer carries the collected licenses', () => {
  const yml = readFileSync(new URL('../electron-builder.yml', import.meta.url), 'utf8')
  assert.match(yml, /from: licenses-out\s+to: licenses/)
  const scripts = JSON.parse(readFileSync(new URL('../../../package.json', import.meta.url), 'utf8')).scripts
  for (const name of ['dist', 'release']) assert.match(scripts[name], /^npm run licenses && /)
})
