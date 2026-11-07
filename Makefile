SHELL := /bin/sh
PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help preflight install setup ffmpeg run build typecheck test engine build-engine dist release

help:
	@printf '%s\n' \
	  'Available targets:' \
	  '  make preflight    Check Node.js, Python, npm, FFmpeg and ffprobe' \
	  '  make install      Install dependencies; on Debian/Ubuntu, install FFmpeg via apt if missing' \
	  '  make setup        Create the Python environment and install engine dependencies' \
	  '  make ffmpeg       Copy ffmpeg and ffprobe from PATH into bin/' \
	  '  make run          Start the desktop app on Windows or Linux (engine starts automatically)' \
	  '  make engine       Run the Python engine by itself on port 8765' \
	  '  make typecheck    Type-check the desktop app' \
	  '  make test         Run the engine test suite' \
	  '  make build        Build the desktop app' \
	  '  make build-engine Build and smoke-test the Python engine' \
	  '  make dist         Build the Windows installer' \
	  '  make release      Build and publish a GitHub release'

preflight:
	@set -eu; \
	for tool in node npm "$(PYTHON)" ffmpeg ffprobe; do \
	  if ! command -v "$$tool" >/dev/null 2>&1; then \
	    printf 'Missing required command: %s\n' "$$tool" >&2; \
	    exit 1; \
	  fi; \
	done; \
	node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 12)) { console.error("Node.js 22.12+ required; found " + process.versions.node); process.exit(1); }'; \
	"$(PYTHON)" -c 'import sys; sys.exit("Python 3.11+ required; found " + ".".join(map(str, sys.version_info[:3])) if sys.version_info < (3, 11) else 0)'; \
	printf 'Preflight passed: Node.js %s, Python %s\n' "$$(node --version)" "$$($(PYTHON) --version 2>&1)"

install:
	@set -eu; \
	if [ "$$(uname -s)" = Linux ] && { ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; }; then \
	  if ! command -v apt-get >/dev/null 2>&1; then \
	    printf 'FFmpeg is missing. Install ffmpeg with your Linux distribution package manager, then rerun "make install".\n' >&2; \
	    exit 1; \
	  fi; \
	  if [ "$$(id -u)" -eq 0 ]; then \
	    apt-get update && apt-get install -y ffmpeg; \
	  elif command -v sudo >/dev/null 2>&1; then \
	    sudo apt-get update && sudo apt-get install -y ffmpeg; \
	  else \
	    printf 'FFmpeg is missing and sudo is unavailable. Install ffmpeg, then rerun "make install".\n' >&2; \
	    exit 1; \
	  fi; \
	fi
	$(MAKE) preflight
	npm install
	npm run setup
	npm run bundle:ffmpeg

setup:
	npm run setup

ffmpeg:
	npm run bundle:ffmpeg

# Electron refuses to start when Chromium's setuid sandbox helper is not
# root-owned with mode 4755. That is normal on NTFS/exFAT drives (no setuid
# support) and after a plain `npm install`, and fixing it needs root. In that
# case fall back to running the app un-sandboxed, which electron-vite enables
# through NO_SANDBOX=1.
run:
	@set -eu; \
	if [ "$$(uname -s)" = Linux ]; then \
	  helper=node_modules/electron/dist/chrome-sandbox; \
	  if [ ! -u "$$helper" ] || [ "$$(stat -c %u "$$helper" 2>/dev/null || echo 1)" -ne 0 ]; then \
	    printf 'Note: Electron sandbox helper is not setuid root (normal on NTFS and new installs);\n' >&2; \
	    printf '      starting with --no-sandbox. To use the sandbox instead, run:\n' >&2; \
	    printf '      sudo chown root:root %s && sudo chmod 4755 %s\n' "$$helper" "$$helper" >&2; \
	    NO_SANDBOX=1 exec npm run dev; \
	  fi; \
	fi; \
	exec npm run dev

engine:
	@if [ -x engine/.venv/bin/python ]; then \
	  cd engine && .venv/bin/python run.py --port 8765; \
	elif [ -x engine/.venv/Scripts/python.exe ]; then \
	  cd engine && .venv/Scripts/python.exe run.py --port 8765; \
	else \
	  printf 'Python environment not found. Run "make setup" first.\n' >&2; \
	  exit 1; \
	fi

typecheck:
	npm run typecheck

test:
	npm run test:engine

build:
	npm run build

build-engine:
	npm run build:engine

dist:
	npm run dist

release:
	npm run release
