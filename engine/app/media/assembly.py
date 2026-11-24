"""Join normalized clip exports, adding silence for parts with no original audio."""

import time
from pathlib import Path

from .. import exports
from . import MediaError
from .probe import probe
from .transcode import run_ffmpeg


def build_collage(db, manager, composition, dest, tools, cancel, report):
    job_ids = composition["jobs"]
    try:
        # A failed collage can be retried using the ordinary source retry button.
        for job_id in job_ids:
            with db.connect() as conn:
                job = exports.get_job(conn, job_id)
                if job and job["status"] in ("failed", "cancelled"):
                    conn.execute("UPDATE export_jobs SET status = 'queued', error = NULL, progress = 0 WHERE id = ?", (job_id,))
                    job = exports.get_job(conn, job_id)
                else:
                    job = None
            if job:
                manager.submit(job)
        while True:
            cancel.raise_if_cancelled()
            with db.connect() as conn:
                jobs = [exports.get_job(conn, job_id) for job_id in job_ids]
            if any(j is None for j in jobs):
                raise MediaError("A collage clip was deleted; create the collage again")
            if any(j["status"] in ("failed", "cancelled") for j in jobs):
                raise MediaError(next(j["error"] or "A collage part was cancelled" for j in jobs if j["status"] in ("failed", "cancelled")))
            report(sum(j["progress"] for j in jobs) / len(jobs) * 0.8)
            if all(j["status"] == "done" for j in jobs):
                break
            time.sleep(0.1)
        args, graph, inputs, duration = [], [], [], 0
        for i, job in enumerate(jobs):
            info = probe(tools.ffprobe.path, Path(job["output_path"]))
            seconds = info.duration_ms / 1000
            duration += info.duration_ms
            args += ["-i", job["output_path"]]
            graph.append(f"[{i}:v]setsar=1,setpts=PTS-STARTPTS[v{i}]")
            audio = f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,apad" if info.has_audio else "anullsrc=r=48000:cl=stereo"
            graph.append(f"{audio},atrim=duration={seconds:.6f},asetpts=PTS-STARTPTS[a{i}]")
            inputs.append(f"[v{i}][a{i}]")
        graph.append("".join(inputs) + f"concat=n={len(jobs)}:v=1:a=1[v][a]")
        graph_file = dest.with_suffix(".graph.txt")
        graph_file.write_text(";".join(graph), encoding="utf-8")
        temporary = dest.with_name("collage.partial.mp4")
        try:
            run_ffmpeg(tools.ffmpeg.path, [*args, "-/filter_complex", str(graph_file), "-map", "[v]", "-map", "[a]",
                       "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", "-movflags", "+faststart", str(temporary)],
                       duration, cancel, lambda p: report(0.8 + p * 0.2))
            temporary.replace(dest)
        finally:
            graph_file.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
    finally:
        for job_id in job_ids:
            manager.cancel(job_id)
