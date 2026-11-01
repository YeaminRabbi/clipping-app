"""Who is talking: follow faces over time and pick the one whose mouth moves while there's speech.

Pure functions (times in ms) so the switching behaviour can be tested precisely. The camera should
behave like a calm editor: cut to a new speaker only once they've clearly been talking for a moment,
hold each shot for a minimum time, and never switch during silence.
"""

from dataclasses import dataclass, field

from .detect import Face

TRACK_RADIUS = 0.12  # a face within this distance of where a track was is the same person
TRACK_FORGET_MS = 2000  # a track not seen for this long is dropped
MIN_TRACK_SHARE = 0.25  # a face must be visible in this share of samples to count as a speaker
ACTIVITY_WINDOW_MS = 800  # mouth movement is averaged over this long
SWITCH_MARGIN = 1.4  # the new speaker must move their mouth this much more than the current one
SWITCH_CONFIRM_MS = 600  # ... for this long before the camera cuts
MIN_SHOT_MS = 2000  # and each speaker shot lasts at least this long


@dataclass
class _Track:
    id: int
    last_t: int
    last: Face


@dataclass
class SpeakerResult:
    subject: list[tuple[int, Face | None]]  # the face to frame at each sample
    switches: list[int] = field(default_factory=list)  # times the camera cuts to another speaker
    speakers: int = 0  # people who were on camera at least once


def assign_tracks(samples: list[tuple[int, list[Face]]]) -> list[tuple[int, dict[int, Face]]]:
    """Give each detected face a stable id across samples by nearest position."""
    tracks: list[_Track] = []
    next_id = 0
    out: list[tuple[int, dict[int, Face]]] = []
    for t, faces in samples:
        tracks = [tr for tr in tracks if t - tr.last_t <= TRACK_FORGET_MS]
        free = list(tracks)
        assigned: dict[int, Face] = {}
        # Biggest faces first, so a close-up keeps its track when a small face passes by.
        for face in sorted(faces, key=lambda f: -f.area):
            best = min(free, key=lambda tr: abs(tr.last.cx - face.cx) + abs(tr.last.cy - face.cy), default=None)
            if best is not None and abs(best.last.cx - face.cx) < TRACK_RADIUS and abs(best.last.cy - face.cy) < TRACK_RADIUS:
                free.remove(best)
                best.last, best.last_t = face, t
                assigned[best.id] = face
            else:
                tracks.append(_Track(id=next_id, last_t=t, last=face))
                assigned[next_id] = face
                next_id += 1
        out.append((t, assigned))
    return out


def pick_speaker(
    tracked: list[tuple[int, dict[int, Face]]],
    activity: dict[tuple[int, int], float],
    speech: list[bool],
) -> SpeakerResult:
    """Per sample, the face of the person talking.

    `activity[(t, track)]` is mouth movement at that sample; `speech[i]` says whether sample i has sound.
    """
    if not tracked:
        return SpeakerResult(subject=[])
    total = len(tracked)
    times = [t for t, _ in tracked]
    seen: dict[int, int] = {}
    for _, faces in tracked:
        for tid in faces:
            seen[tid] = seen.get(tid, 0) + 1
    # People who are on screen for a meaningful part of the clip; passers-by never get the camera.
    candidates = {tid for tid, n in seen.items() if n >= total * MIN_TRACK_SHARE}

    step = (times[-1] - times[0]) / max(total - 1, 1) if total > 1 else 100
    half = max(1, round(ACTIVITY_WINDOW_MS / step / 2))

    def smoothed(i: int, tid: int) -> float:
        lo, hi = max(0, i - half), min(total, i + half + 1)
        values = [activity.get((times[j], tid), 0.0) for j in range(lo, hi) if speech[j]]
        return sum(values) / len(values) if values else 0.0

    # Pass 1: who is on camera from when. Each entry is (start time, track id).
    shots: list[tuple[int, int]] = []
    challenger: tuple[int, int] | None = None  # (track, time they started out-talking the current one)
    for i, (t, faces) in enumerate(tracked):
        visible = [tid for tid in faces if tid in candidates]
        current = shots[-1][1] if shots else None
        if current is None or current not in visible:
            # Start, or the speaker left the frame: take whoever is most active now (else the biggest face).
            if visible:
                best = max(visible, key=lambda tid: (smoothed(i, tid), faces[tid].area))
                if best != current:
                    shots.append((t, best))
                challenger = None
            continue
        if not speech[i] or len(visible) < 2:
            challenger = None
            continue
        scores = {tid: smoothed(i, tid) for tid in visible}
        best = max(scores, key=lambda tid: scores[tid])
        if best != current and scores[best] > SWITCH_MARGIN * max(scores[current], 1e-6):
            if challenger is None or challenger[0] != best:
                challenger = (best, t)
            elif t - challenger[1] >= SWITCH_CONFIRM_MS and challenger[1] - shots[-1][0] >= MIN_SHOT_MS:
                # Cut at the moment they started talking, so the picture doesn't lag behind the voice.
                shots.append((challenger[1], best))
                challenger = None
        else:
            challenger = None

    # Pass 2: the chosen person's face at every sample (held through brief detection gaps).
    subject: list[tuple[int, Face | None]] = []
    shot_i = 0
    last_face: Face | None = None
    for t, faces in tracked:
        while shot_i + 1 < len(shots) and t >= shots[shot_i + 1][0]:
            shot_i += 1
            last_face = None
        tid = shots[shot_i][1] if shots else None
        face = faces.get(tid) if tid is not None else None
        last_face = face or last_face
        subject.append((t, face or last_face))
    return SpeakerResult(
        subject=subject,
        switches=[start for start, _ in shots[1:]],
        speakers=len({tid for _, tid in shots}),
    )
