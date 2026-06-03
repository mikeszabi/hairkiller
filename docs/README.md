# HairKiller Docs

Start here when choosing which document to use.

## API And App Docs

- `RESTAPI_definition.ini`: current endpoint catalog for `backend/hk_backend_app.py`, grouped by subsystem and frontend workflow.
- `hk_backend_app_api.md`: consolidated backend overview, frontend descriptions, treatment-only UI behavior, cleanup/emergency stop behavior, and performance notes.
- `hk_full_app_api.md`: detailed full-app and legacy workflow notes. It covers the route families still used by the full portrait app and lower-level tools.

## Firmware / Serial Docs

- `stm_command_reference_from_code.xlsx`: command reference generated from the firmware command metadata used by `code/serial_commands.py`.
- `README_serial.md`: older serial protocol notes and hardware testing context. Prefer the generated command catalog in the backend for current command names when they differ.

## Current Frontends

- `app/index.html`: frontend launcher.
- `app/hk_treatment_app_portrait.html`: simplified treatment-only operator UI.
- `app/hk_full_app_portrait.html`: full operator and diagnostics UI.
- `app/hk_calibration_app_portrait.html`: calibration UI.
- `app/hk_camera_test.html`: camera diagnostics UI.
- `app/hk_full_app_check.html`: preflight/status UI.

Every API endpoint works at both `/path` and `/api/path`.
