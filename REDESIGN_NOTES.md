# Redesign notes (25 Nov 2026)

This applies the approved navy glass redesign to the desktop app's interface. Engine code is unchanged.

## What changed
- **Theme** (`index.css`): navy glass colours, white pill buttons with dark text, rounder panels, and a soft background glow. Blur is used only on the sidebar and dialogs, and the video preview stays solid.
- **Floating sidebar** (`components/Sidebar.tsx`): the logo, Projects (home), the engine status dot (opens Settings) and Settings. The old top bar is gone.
- **Home** (`components/Projects.tsx`): project cards in a grid, plus a **New project** button.
- **New project dialog** (`components/NewProjectDialog.tsx`): pick or drop videos; the project name fills in from the first file; **Find clips when the import finishes** is ticked by default; **Create project** opens the project with the videos importing. Dropping a video anywhere on the home screen opens this dialog.
- **Find clips when ready:** while a video is importing, its row has a switch for this. When the import finishes, Find clips runs with your last Find clips settings. The queue lasts for the current session only: if you restart the app mid-import, start Find clips from the video's row.
- **Settings** (`components/SettingsView.tsx`): System check (wide) next to Storage and Updates (narrow).
  - **Storage:** the export location can be changed or reset (each project exports into its own folder there). App data and logs can be opened.
  - **Updates:** check now, download, restart to update. Nothing installs without asking.
- **Project page:** a breadcrumb and a larger title, with restyled panels and video rows.
- **Dialogs:** glass frame with a header strip and dashed footer.

## Not built yet (needs engine work first)
- Moving or clearing app data and caches.
- Gameplay mode, facecam detection, clip scores, the Transcript and Thumbnail editor tabs, and the Shorts package export (see SHORTS_DESIGN.md).
