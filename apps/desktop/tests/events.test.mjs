import assert from 'node:assert/strict'
import { mock, test } from 'node:test'
import { keepConnected } from '../src/renderer/src/lib/events.ts'

function setup() {
  const sockets = []
  const events = []
  let reconnects = 0
  const stop = keepConnected(
    () => {
      const socket = { onopen: null, onmessage: null, onclose: null, closed: false, close() { this.closed = true; this.onclose?.() } }
      sockets.push(socket)
      return socket
    },
    (event, data) => events.push([event, data]),
    () => reconnects++
  )
  return { sockets, events, stop, reconnects: () => reconnects }
}

test('delivers events and ignores malformed ones', () => {
  const t = setup()
  t.sockets[0].onopen()
  t.sockets[0].onmessage({ data: '{"event":"clip","data":{"id":1}}' })
  t.sockets[0].onmessage({ data: 'not json' })
  assert.deepEqual(t.events, [['clip', { id: 1 }]])
  assert.equal(t.reconnects(), 0)
  t.stop()
})

test('reconnects after a drop, waiting longer each time, and then asks for what was missed', () => {
  mock.timers.enable({ apis: ['setTimeout'] })
  const t = setup()
  t.sockets[0].onopen()
  t.sockets[0].onclose()
  mock.timers.tick(499)
  assert.equal(t.sockets.length, 1)
  mock.timers.tick(1)
  assert.equal(t.sockets.length, 2)
  t.sockets[1].onclose() // the engine isn't answering yet
  mock.timers.tick(999)
  assert.equal(t.sockets.length, 2)
  mock.timers.tick(1)
  t.sockets[2].onopen()
  assert.equal(t.reconnects(), 1)
  t.sockets[2].onmessage({ data: '{"event":"x","data":2}' })
  assert.deepEqual(t.events, [['x', 2]])
  t.stop()
  mock.timers.reset()
})

test('stops for good when asked', () => {
  mock.timers.enable({ apis: ['setTimeout'] })
  const t = setup()
  t.stop()
  assert.ok(t.sockets[0].closed)
  mock.timers.tick(60_000)
  assert.equal(t.sockets.length, 1)
  mock.timers.reset()
})
