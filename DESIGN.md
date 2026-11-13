# Themis Orca panel

The operator uses the panel next to Orca's 3D view, so match the active Orca theme rather than selecting an independent
light or dark mode. Follow the official Dock Panel Demo's compact host-native layout.

- Inherit host typography and native form styling. Use `--orca-bg`, `--orca-fg`, `--orca-muted`, `--orca-border`,
  `--orca-accent`, and `--orca-accent-fg` for surfaces and text.
- Use a restrained palette, host accent for actions, and text descriptions for all states.
- Stack current plate and connection status, connection settings, the send action and inspection controls, and reference-data
  summary in a 360-DIP dock. Show existing/new-project and object fields only for the selected action. Put optional eligibility,
  process/override and filament settings in a disclosure, preserving the user's choices across periodic state updates.
- For G-code, replace geometry inspection/settings with an explicit captured-export picker, capture instructions,
  and an editable model selected from the captured profile. Preserve the selection across polling. Show stale/unknown matches and prior
  submission clearly; never make a new capture trigger a network send.
- Use 12px outer padding, 8px field gaps, and larger separation between sections. Avoid nested cards and fixed-width content.
- Keep editable fields labeled, the key masked by default with an explicit reveal option and normal clipboard shortcuts,
  actions keyboard-accessible, and status updates in polite live regions. Show saved-send status and recovery actions.
- No images, custom font downloads, remote assets, or decorative animations are needed for this utility panel.
