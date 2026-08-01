# Hermes Deals UI Reference Rebuild V6

V6 removes the independent desktop sidebar scroll area.

## Contract

- The browser page owns the only vertical scrollbar.
- The desktop sidebar remains sticky but uses content height.
- The sidebar has no `overflow:auto`, `overflow-y:auto`, viewport-locked
  height, or nested overscroll behavior.
- Navigation and utility blocks are compact enough for short desktop
  viewports.
- The existing mobile breakpoint still hides the desktop sidebar.
- Production, the production database, and the Review UI are unchanged.
