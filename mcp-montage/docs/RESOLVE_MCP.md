# DaVinci Resolve adapter status

DaVinci Resolve is an optional finishing adapter, not the state store of the video factory.

## Current status

The previous Cursor/Grok bridge and the experimental Codex bridge were removed from the Resolve Scripts menu. No bridge script is currently installed.

The third-party HTTP bridge could obtain a valid internal Resolve `PyRemoteObject` during script startup, but its methods became unavailable after entering the blocking HTTP loop. A second experiment attempted to marshal calls through Fusion's UI dispatcher; this Resolve build exposed no live `UIManager` from a Workspace utility script while running on the Edit page.

These experiments are preserved under `lab/`; they are not production dependencies and should not be launched manually.

## Operating decision

The active pipeline uses FFmpeg for ingest, rough cuts, captions, preview renders and QC. Resolve integration returns in M3 as a separate adapter only after it can pass an autonomous preflight:

1. obtain product/version;
2. read the current project and timeline;
3. perform a reversible marker operation in a disposable project;
4. restart and reconnect without manual script clicking;
5. report failures without blocking the FFmpeg path.

Until those checks pass, no user action inside Resolve is required.
