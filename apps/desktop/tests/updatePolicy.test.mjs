// Run with: npm run test:desktop
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { updatePolicy } from '../src/main/updatePolicy.ts'

const UNSIGNED = 'owner: someone\nrepo: clipping-app\nprovider: github\nreleaseType: release\nupdaterCacheDirName: x\n'

test('an unsigned build never downloads or installs on its own', () => {
  const policy = updatePolicy(UNSIGNED)
  assert.deepEqual(policy, { verified: false, autoDownload: false, autoInstallOnAppQuit: false })
})

test('a missing or unreadable update file counts as unsigned', () => {
  assert.equal(updatePolicy(null).autoInstallOnAppQuit, false)
  assert.equal(updatePolicy('').verified, false)
})

test('an empty publisher counts as unsigned', () => {
  for (const value of ['', '[]', 'null', '~', '""', "''"]) {
    assert.equal(updatePolicy(`${UNSIGNED}publisherName: ${value}\n`).verified, false, value)
  }
})

test('a signed build may update on its own, because the signature is checked', () => {
  assert.equal(updatePolicy(`${UNSIGNED}publisherName: Example Ltd\n`).autoInstallOnAppQuit, true)
  assert.equal(updatePolicy(`${UNSIGNED}publisherName:\r\n  - Example Ltd\r\n`).verified, true)
})
