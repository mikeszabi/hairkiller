# hk_backend_app API Reference

`backend/hk_backend_app.py` is the consolidated HairKiller FastAPI backend for camera streaming, detection, calibration, treatment, laser control, target sequencing, vacuum control, and firmware diagnostics.

Run the production backend:

```bash
uvicorn backend.hk_backend_app:app --host 0.0.0.0 --port 8000
```

Run the mock backend:

```bash
uvicorn backend.hk_backend_mock_app:app --host 0.0.0.0 --port 8000
```

Every API route is available at the direct path and under `/api/...`. The HTML frontends infer `/api` automatically when served separately from FastAPI.

## Frontends

- `app/index.html`: frontend launcher. Passes `?api=...` through to each app.
- `app/hk_full_app_portrait.html`: full operator UI with camera, treatment, calibration support panels, app errors, serial command tools, laser test tools, sequence controls, and sensors.
- `app/hk_treatment_app_portrait.html`: simplified treatment-only portrait UI. It is button-driven, does not poll state continuously, and exposes `AUTO`, `SEMI-AUTO`, `MANUAL`, `DETECT`, `FIRE`, `NEXT`, cleanup, emergency stop, laser power/pulse, detection threshold, live overlay, vacuum, arm/disarm, state check, and laser temperature.
- `app/hk_calibration_app_portrait.html`: red-dot calibration and homography workflow.
- `app/hk_camera_test.html`: camera diagnostics, settings, snapshot, and latency tooling.
- `app/hk_full_app_check.html`: backend/hardware preflight check UI.

The production backend serves:

- `GET /`
- `GET /hk_full_app_check.html`
- `GET /hk_treatment_app_portrait.html`

Most deployment setups copy the static files from `app/` to a web server and point them at `http://<backend>:8000/api`.

## Startup And Safety State

On backend startup, and whenever the frontend calls `POST /startup/clean_state`, the backend attempts to put the microcontroller and UI runtime into a clean state:

- app errors cleared
- target errors cleared
- target sequence stopped/halted where possible
- target list cleared
- laser stopped and disarmed
- red dot off
- hair detection off
- live detection overlay off
- treatment runtime reset
- async error/event buffers cleared
- `APP_STATE` checked before/after cleanup

`POST /treatment/app/emergency_stop` performs an immediate treatment stop path:

- target halt/stop
- laser stop/disarm
- vacuum off
- cleanup states

## Treatment-Only API

The treatment-only portrait UI uses `/treatment/app/...` endpoints. These endpoints intentionally avoid expensive status fan-out after fast actions. Operators use `CHECK STATES`, which calls `GET /treatment/app/status`, only when needed.

### `GET /treatment/app/status`

Returns a compact state snapshot for the treatment UI:

- treatment mode/status
- `APP_STATE`
- app last error
- `TARGET_GET_STATE`
- target last error
- laser arm state
- local laser power/pulse
- detection enabled/threshold/live-overlay state
- loaded target count
- vacuum output/check state

This endpoint performs multiple serial queries and should not be polled continuously.

### `POST /treatment/app/mode?mode=...`

Modes:

- `auto`: detects and fires when vacuum is ON. Triggered by the backend auto worker.
- `semi_auto`: two phases: `DETECT` uploads targets, then `FIRE` starts the loaded sequence.
- `manual`: two phases: `DETECT` uploads targets in manual mode, then `NEXT` fires/continues one target at a time.

### `POST /treatment/app/detect`

For `semi_auto` and `manual`.

Behavior:

- If live detection is enabled and a background inference cache is available, uses cached centers for speed.
- Otherwise runs synchronous detection on the latest frame.
- Converts detected image points to galvo targets.
- Uploads targets to the controller.
- Does not perform full state refresh after upload.

Performance:

- Fastest when `POST /detection/toggle?enabled=true` is already on.
- Target upload is one serial command per target. Limit is `_max_sequence_targets`, currently `50`.
- Per-target serial waits are controlled by `HK_TARGET_LOAD_WAIT_S` and `HK_TARGET_LOAD_READ_WINDOW_S`.

### `POST /treatment/app/fire`

For `semi_auto`.

Behavior:

- Requires targets already loaded by `DETECT`.
- Requires vacuum ON, laser ARMED, nonzero laser power, pulse set, target idle, target error clear.
- Sends `TARGET_START`.
- Does not perform full state refresh after start.

### `POST /treatment/app/next`

For `manual`.

Behavior:

- Requires manual treatment runtime from `DETECT`.
- Requires vacuum ON, laser ARMED, nonzero laser power, target not busy, target error clear.
- Starts or continues the target sequence for the next point.

### `POST /treatment/app/settings?p808=...&p980=...&p1064=...&pulse_ms=...`

Sets treatment laser power and target pulse. If targets are already loaded, reloads them so target entries contain the current power/pulse values.

### `POST /treatment/app/emergency_stop`

Stops target process, disarms/stops laser, turns vacuum off, and calls cleanup states.

## Detection And Overlays

- `POST /detection/toggle?enabled=true|false`: turns background YOLO inference on/off.
- `POST /detection/conf?conf=0.25`: sets threshold, clamped to `0.01..1.0`, and clears cached inference.
- `POST /detection/live_overlay?enabled=true|false`: controls whether live YOLO boxes are drawn on `/frame/current`; detection can remain enabled without drawing overlay.
- `POST /detection/capture`: one synchronous detection pass.
- `GET /detection/status`: threshold, live-overlay, red-dot, HSV, and detection flags.

## Camera And Diagnostics

- `GET /health`
- `GET /stats`
- `GET /frame/meta`
- `GET /frame/current`
- `GET /frame/snapshot`
- `GET /camera/settings`
- `POST /camera/settings`
- `GET /camera/frame_stride`
- `POST /camera/frame_stride?value=2`
- `POST /latency/benchmark`
- `GET /diagnostics/full_app_check`

`frame_stride` controls stream/inference downsampling. The stream resolution is `960x960`; native cropped camera coordinates are `1920x1920`.

## Calibration

- `POST /calibration/detection/toggle?enabled=true|false`
- `POST /detection/mask_overlay?enabled=true|false`
- `GET /detection/hsv`
- `POST /detection/hsv?...`
- `GET /dot`
- `GET /frame/hsv?x=...&y=...`
- `GET /sse/dot`
- `POST /calibration/start`
- `POST /calibration/store`
- `GET /calibration/points`
- `POST /calibration/save`
- `POST /homography/reload`

`/frame/current` is shared by all frontends and may show treatment target overlays, live hair detection overlay, calibration red-dot overlay, and HSV mask overlay depending on flags.

## Laser, Vacuum, Target, Galvo

Detailed route lists live in `docs/RESTAPI_definition.ini`.

Main route families:

- `/laser/...`
- `/vacuum/...`
- `/seq/...`
- `/mover/...`
- `/coords/convert`
- `/walk/...`
- `/fire/walk`
- `/app/...`

## Mock Backend

`backend/hk_backend_mock_app.py` mirrors the route surface needed by the HTML apps:

- `/api` prefix support
- synthetic camera stream and snapshots
- simulated treatment, detection, vacuum, laser, target, and calibration state
- no hardware required

Use it for frontend development when serial hardware is unavailable.

## Performance Notes

Serial command latency dominates many control flows. `SerialDevice.query()` waits after sending a command and then waits for an extra read window. Avoid polling multi-query state endpoints.

Treatment UI behavior:

- Fast actions avoid full state fan-out.
- `CHECK STATES` is explicit because it performs multiple serial queries.
- `DETECT` is fastest with live detection enabled because it can reuse the cached background inference.
- `FIRE` is fastest when settings are already applied and target points are already loaded.
- Target upload is one command per target; fewer targets are faster.
