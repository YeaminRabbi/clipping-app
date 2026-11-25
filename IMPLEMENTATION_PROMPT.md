# Prompt for the coding agent

Copy the following into your coding agent, run from the app's project folder, after unzipping this folder into the project root as `design/`.

---

Read `design/DESIGN_SPEC.md`, `design/tokens.css` and the screen sources in `design/screens/` (they are prototype files written in a template format: use them as a visual and behavioural reference, not as code to copy). Also read `SHORTS_DESIGN.md` and `FIX_REPORT.md`.

## Safety rules (apply to everything)
- Do not install or update GPU drivers, CUDA, or anything system-wide (no winget or choco). If something is missing, stop and tell me.
- Keep all dependencies, caches and outputs inside the project folder.
- Never modify, move or delete my original video files.
- Commit the current state first, then commit each step separately.

## Task: implement the approved redesign
1. **Plan first.** Map each screen and component in the spec to the current codebase: which files change, and which shadcn/ui components and Hugeicons icons you'll use. Check whether the UI is React. If it isn't, tell me and propose the closest equivalent before going further. Check the Hugeicons free-set license and tell me what it says before installing it. Write the plan to `REDESIGN_PLAN.md` and wait for my go-ahead.
2. **Then build, in this order:**
   1. Design tokens and the glass styles. Apply blur only to the sidebar and dialogs; the video preview and timeline must stay solid.
   2. Floating sidebar: logo, Home, engine status dot, Settings. Remove the old top bar.
   3. Home: project cards and the New project dialog (drop zone, auto-filled name, "Find clips when the import finishes" checkbox, Create disabled until a file is added). Dropping a file anywhere in the app opens this dialog.
   4. Project page: video rows with live import and auto-clip progress steps, and the restyled Find clips dialog with the new Gameplay stream mode and Facecam options.
   5. Editor: restyle, then add the score pills, the Transcript and Thumbnail tabs, the facecam switch and box, and Edit framing / Preview output.
   6. Export dialog with the Shorts package option, following the handoff package format in SHORTS_DESIGN.md.
   7. Settings: the 80/20 layout, System check with Restart engine, Storage (change location, two-step clear for app data and cache only), and Updates (manual only).
3. Where a feature needs engine work that doesn't exist yet (scores, transcript tab, thumbnails, facecam detection, auto clipping), build the UI against the planned data shapes from SHORTS_DESIGN.md and show a clear "coming soon" or empty state. Don't fake data in the real app.
4. Keep everything accessible: real buttons and inputs, labels on icon-only buttons, the right roles on toggles and tabs, and text contrast of at least 4.5:1.
5. Run the full test suite after each step. Nothing that passed before may fail.

When done, write `REDESIGN_REPORT.md`: what was built, what's still placeholder, screenshots of each screen if you can take them, and test counts before vs. after.
