import assert from 'node:assert/strict'
const {
  acquirePreviewAudioGraph,
  applyPreviewAudioGain,
  clipExportGain,
  monitorVolumeFromStorage,
  previewGain,
  releasePreviewAudioGraph,
  resumePreviewAudio
} = await import('../src/renderer/src/lib/audio.ts')

assert.equal(monitorVolumeFromStorage(null), 100, 'an absent preference must not initialize playback at 0%')
assert.equal(monitorVolumeFromStorage(''), 100)
assert.equal(monitorVolumeFromStorage('not-a-number'), 100)
assert.equal(monitorVolumeFromStorage('0'), 0, 'an explicit user-selected 0% must be preserved')
assert.equal(monitorVolumeFromStorage('65'), 65)

const boosted = { level: 150, muted: false }
assert.equal(previewGain(100, false, { level: 100, muted: false }), 1, '100% x 100% must preserve original playback level')
assert.equal(clipExportGain(boosted), 1.5)
assert.equal(previewGain(50, false, boosted), 0.75)
assert.equal(previewGain(50, true, boosted), 0)
assert.equal(clipExportGain(boosted), 1.5, 'monitoring mute must not affect export')
assert.equal(clipExportGain({ level: 150, muted: true }), 0)
assert.equal(previewGain(100, false, { level: 250, muted: false }), 2)

const video = { volume: 0, muted: true }
applyPreviewAudioGain(video, null, 0.5)
assert.equal(video.volume, 0.5, '50% must map to HTML media volume 0.5')
assert.equal(video.muted, false)
applyPreviewAudioGain(video, null, 0)
assert.equal(video.volume, 0)
assert.equal(video.muted, true)

let contextsCreated = 0
const calls = { resumed: 0, closed: 0, sourceDisconnected: 0 }
const audioParam = () => ({ value: 0, setTargetAtTime(value) { this.value = value } })
const destination = {}
const context = {
  state: 'suspended',
  currentTime: 0,
  destination,
  createMediaElementSource() {
    return { connect: () => gainNode, disconnect: () => calls.sourceDisconnected++ }
  },
  createGain() {
    return gainNode
  },
  createDynamicsCompressor() {
    return limiterNode
  },
  async resume() {
    calls.resumed++
    this.state = 'running'
  },
  async close() {
    calls.closed++
    this.state = 'closed'
  }
}
const gainNode = { gain: audioParam(), connect: () => limiterNode, disconnect() {} }
const limiterNode = {
  threshold: audioParam(), knee: audioParam(), ratio: audioParam(), attack: audioParam(), release: audioParam(),
  connect: () => destination, disconnect() {}
}
const graphVideo = { volume: 0, muted: true }
const createContext = () => {
  contextsCreated++
  return context
}
const firstGraph = acquirePreviewAudioGraph(graphVideo, createContext)
releasePreviewAudioGraph(graphVideo, firstGraph)
const strictModeGraph = acquirePreviewAudioGraph(graphVideo, createContext)
assert.equal(strictModeGraph, firstGraph, 'Strict Mode effect rerun must reuse the existing media source')
assert.equal(contextsCreated, 1, 'a video element may only have one MediaElementSource')
await new Promise((resolve) => setTimeout(resolve, 5))
assert.equal(calls.closed, 0, 'the reacquired graph must remain connected')
applyPreviewAudioGain(graphVideo, strictModeGraph, 1)
assert.equal(graphVideo.volume, 1)
assert.equal(graphVideo.muted, false)
assert.equal(gainNode.gain.value, 1)
await resumePreviewAudio(strictModeGraph)
assert.equal(calls.resumed, 1)
releasePreviewAudioGraph(graphVideo, strictModeGraph)
await new Promise((resolve) => setTimeout(resolve, 5))
assert.equal(calls.closed, 1)
assert.equal(calls.sourceDisconnected, 1)

console.log('Audio control independence checks passed.')
