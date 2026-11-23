"""Check pinned requirements using only the standard library, before the engine can import."""

import importlib.metadata
import importlib.util
import re
import sys
from pathlib import Path


def missing_requirements(path: Path) -> list[str]:
    missing = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            missing.extend(missing_requirements(path.parent / line[3:].strip()))
            continue
        match = re.fullmatch(r"([\w.-]+)(?:\[[\w,.-]+\])?==([^\s]+)", line)
        if not match:
            raise ValueError(f"Unsupported requirement in {path}: {line}")
        name, expected = match.groups()
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != expected:
            missing.append(line)
    return missing


def main() -> int:
    requirements = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("requirements.txt")
    problems = missing_requirements(requirements)
    # Metadata can survive an incomplete installation; check that entry modules exist too.
    for module in ("fastapi", "uvicorn", "yt_dlp", "numpy", "cv2", "faster_whisper"):
        if importlib.util.find_spec(module) is None:
            problems.append(f"Missing module: {module}")
    if problems:
        print("\n".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
