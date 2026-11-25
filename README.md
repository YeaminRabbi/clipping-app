# Clipping App redesign: handoff package

Approved 25 Nov 2026. Live prototype: https://claude.ai/artifact/1S51cS7FqCScmoHS8UVKSv

| File | What it is |
|---|---|
| `DESIGN_SPEC.md` | The full spec: look, layout, every screen's behaviour, shadcn/Hugeicons mapping, accessibility |
| `tokens.css` | Colours, radii, type sizes and glass styles as CSS variables |
| `IMPLEMENTATION_PROMPT.md` | The prompt to give your coding agent to build it |
| `screens/` | Prototype source for Home, Project, Editor and Settings (reference only; written in a design-canvas template format) |

How to use it:
1. Unzip this folder into the app's project root and rename it `design/`.
2. Paste the prompt from `IMPLEMENTATION_PROMPT.md` into your coding agent.
3. Review the `REDESIGN_PLAN.md` it writes before letting it build.
