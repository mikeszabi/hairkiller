# Full App And Legacy Workflow API Reference

The current production backend is `backend/hk_backend_app.py`. This document describes the full-application and legacy workflow endpoints that are still used by `app/hk_full_app_portrait.html` and related tools.

Default local URL when started with Uvicorn:

```bash
uvicorn backend.hk_backend_app:app --host 0.0.0.0 --port 8000
```

Base URL examples in this document use `http://localhost:8000`.
The backend also accepts the same endpoints under `http://localhost:8000/api/...` so external frontends can use a stable API prefix.

## Runtime Model

- The root page `/` serves the legacy full app file when available.
- `GET /hk_full_app_check.html` serves the preflight/status UI.
- `GET /hk_treatment_app_portrait.html` serves the simplified treatment-only UI.
- The same API is reachable with or without the `/api` prefix.
- CORS is open to all origins.
- Most write endpoints use query parameters, not JSON bodies.
- The raw-command endpoint and laser settings endpoint use JSON request bodies.
- Camera capture runs continuously in `UVCInterface`.
- Detection inference runs in a background thread only while detection is enabled.
- Live detection drawing is controlled separately by `/detection/live_overlay`; detection can be enabled while the camera stream remains clean.
- The displayed stream is resized to `960x960`; native cropped camera coordinates are `1920x1920`.
- Galvo and target coordinates are clamped by the handler layer to `0..4095`.
- Laser, target, and galvo operations depend on the serial controller being available.

## Common Responses

Successful controller endpoints usually return raw serial response lines under `response`:

```json
{
  "response": ["[LASER_GET_STATE]->[LASER_STATE_ARMED_IDLE][12523]"]
}
```

Application validation or unavailable hardware errors are JSON error objects with an HTTP error status:

```json
{
  "error": "Laser unavailable"
}
```

Common hardware errors:

- `500 {"error":"Laser unavailable"}` when the laser serial interface failed to initialize.
- `500 {"error":"Target controller unavailable"}` when the target interface is unavailable.
- `500 {"error":"Galvo unavailable"}` when galvo control is unavailable.
- `400 {"error":"Homography unavailable"}` or `500 {"error":"Homography not available"}` when coordinate conversion cannot run.
- `400 {"error":"No points"}` when a sequence/walk operation needs detected points.

## UI And Diagnostics

### `GET /`

Returns the legacy/root full application HTML UI as a file response.

### `GET /hk_full_app_check.html`

Returns the preflight/status HTML UI as a file response.

### `GET /hk_treatment_app_portrait.html`

Returns the simplified treatment-only portrait UI as a file response.

### `GET /health`

Checks basic backend readiness.

Response:

```json
{
  "ok": true,
  "camera_ready": true,
  "laser_ready": true,
  "target_ready": true,
  "galvo_ready": true,
  "detector_ready": true,
  "homography_loaded": true,
  "last_frame_index": 123,
  "frame_age_ms": 20.5
}
```

### `GET /stats`

Returns camera stats/settings plus app state flags.

Response fields:

- `camera`: frame index, read failures, frame age, interval min/avg/max, measured FPS.
- `settings`: negotiated OpenCV camera settings.
- `stream`: `width`, `height`, `window_s`.
- `detection_enabled`, `detection_count`, `red_dot_enabled`, `homography_loaded`, `detected_points`, `walking`.

### `GET /frame/meta`

Returns metadata for the latest cropped camera frame.

Response:

```json
{
  "ok": true,
  "frame_index": 123,
  "width": 1920,
  "height": 1920,
  "stream_width": 960,
  "stream_height": 960,
  "frame_age_ms": 18.2
}
```

Returns `503` when no camera frame is available.

## Camera Stream And SSE

### `GET /frame/current`

Returns a multipart MJPEG stream:

```text
Content-Type: multipart/x-mixed-replace; boundary=frame
```

Each frame may include:

- Green detection boxes and yellow center markers when detection and live overlay are enabled.
- Yellow loaded target overlays when `/seq/show_targets?enabled=true` is active.
- Calibration red-dot and HSV mask overlays when calibration overlay flags are active.
- Red crosshair for the current walking target.

### `GET /sse/detection`

Server-Sent Events stream for detection count changes.

Event data:

```json
{"type":"detection_count","count":7}
```

### `GET /sse/galvo_pos`

Server-Sent Events stream for galvo position changes.

Event data:

```json
{"x":3000,"y":3000}
```

## Detection And Points

### `POST /detection/toggle`

Enables or disables background hair detection.

Query parameters:

- `enabled` boolean, required.

Example:

```bash
curl -X POST "http://localhost:8000/detection/toggle?enabled=true"
```

Response:

```json
{"detection_enabled":true,"conf":0.1}
```

### `GET /detection/status`

Returns detection, live overlay, threshold, red-dot, and HSV state.

```json
{
  "detection_enabled": true,
  "hair_detection_enabled": true,
  "hair_detection_overlay_enabled": true,
  "conf": 0.1,
  "red_dot": false
}
```

### `POST /detection/conf`

Sets detector confidence. The backend clamps the value to `0.01..1.0`.
Changing confidence clears the cached background inference result.

Query parameters:

- `conf` float, required.

Response:

```json
{"conf":0.25}
```

### `POST /detection/live_overlay`

Shows or hides live YOLO boxes on `/frame/current` without turning background detection on/off.

Query parameters:

- `enabled` boolean, required.

Response:

```json
{"hair_detection_overlay_enabled":true}
```

### `POST /detection/capture`

Runs detection on the latest camera frame and stores detected center points in memory.

Response:

```json
{
  "captured": 2,
  "points": [[512,640],[900,701]]
}
```

If no boxes are found:

```json
{"captured":0,"points":[]}
```

### `GET /points/list`

Returns the currently stored captured image points.

```json
{"points":[[512,640],[900,701]],"count":2}
```

### `POST /points/clear`

Clears stored detected points.

```json
{"status":"cleared"}
```

## Coordinates And Homography

### Coordinate Spaces

- Stream click coordinates are `960x960`.
- Native cropped image coordinates are `1920x1920`.
- `/mover/move_image` expects stream coordinates and scales them to native coordinates before homography conversion.
- `/coords/convert`, detection capture, walking, and sequence update use native image coordinates.
- Galvo coordinates are integer target positions, normally `0..4095`.

### `GET /coords/convert`

Converts a native image point to galvo coordinates using the loaded homography.

Query parameters:

- `ix` integer, required.
- `iy` integer, required.

Response:

```json
{"x":2871,"y":3040}
```

### `POST /homography/reload`

Reloads the homography matrix from `transformation_matrix.txt`.

Response:

```json
{"status":"reloaded"}
```

## Galvo Mover

### `GET /mover/pos`

Returns the backend's current commanded galvo position.

```json
{"x":3000,"y":3000}
```

### `POST /mover/move`

Moves the galvo to explicit galvo coordinates.

Query parameters:

- `x` integer, required.
- `y` integer, required.

Response:

```json
{"new_position":[2500,2600]}
```

### `POST /mover/direction`

Moves the galvo relative to the current commanded position.

Query parameters:

- `direction` string, required. Supported values in code: `up`, `down`, `left`, `right`.
- `step` integer, optional, default `25`.

Response:

```json
{"new_position":[3000,2975]}
```

Unsupported directions currently result in no coordinate change and still call the move function.

### `POST /mover/move_image`

Converts a stream image coordinate to native image coordinates, transforms it to galvo coordinates, and moves the galvo.

Query parameters:

- `x` integer, required. Stream coordinate in `0..960`.
- `y` integer, required. Stream coordinate in `0..960`.

Response:

```json
{
  "image": [480,480],
  "native_image": [960,960],
  "target": [2871,3040],
  "new_position": [2871,3040]
}
```

## Walking Detected Points

Walking is a backend-side loop over captured points. It optimizes point order with a simple nearest-neighbor path, transforms image points to galvo coordinates, and moves the galvo to each target.

### `POST /walk/start`

Starts walking through stored detected points.

Response:

```json
{
  "status": "completed",
  "visited": [
    {"target":[2871,3040],"actual":[2871,3040]}
  ]
}
```

### `POST /walk/stop`

Requests the active walking loop to stop.

Response:

```json
{"status":"stopped"}
```

## Laser Control

### Safety Notes

- Arming through `/laser/arm` or `/laser/arm_en?enabled=true` first tries to enable Peltier cooling if it is not already enabled.
- Power values are clamped in `LaserInterface` to `0..100`.
- Fire duration is clamped in `LaserInterface` to `10..1000` ms.
- The firmware may reject laser operations when the app is not in `RUNNING`, another process is active, or vacuum checks fail.

### `POST /laser/arm_en`

Sets arm state.

Query parameters:

- `enabled` boolean, required.

Response:

```json
{
  "response": ["[LASER_SET_ARM_EN][1]->[OK][12523]"],
  "enabled": true,
  "peltier": {
    "status": ["[PELTIER_GET_COOLING_EN]->[1][12523]"],
    "enable": null,
    "enabled": true
  }
}
```

### `GET /laser/arm_en`

Reads arm enabled state.

```json
{"response":["[LASER_GET_ARM_EN]->[1][12523]"]}
```

### `POST /laser/arm`

Enables Peltier cooling if needed and arms the laser.

### `POST /laser/disarm`

Disarms the laser.

### `POST /laser/ack`

Acknowledges/clears laser errors through the laser interface.

### `POST /laser/clear_error`

Clears laser error and resets backend red-dot state to false.

### `GET /laser/last_error`

Reads the last laser error.

### `POST /laser/pwr`

Sets one logical laser channel power.

Query parameters:

- `laser_id` integer, required. `1=1064`, `2=980`, `3=808`, `4=all`.
- `pwr` integer, required. Clamped to `0..100`.

Response:

```json
{"response":["[LASER_SET_CHANNEL_PWR][20,20,20]->[OK][12523]"]}
```

### `POST /laser/channel_pwr`

Sets explicit wavelength powers.

Query parameters:

- `p808` integer, required.
- `p980` integer, required.
- `p1064` integer, required.

Response:

```json
{
  "response": ["[LASER_SET_CHANNEL_PWR][20,25,50]->[OK][12523]"],
  "power": {"p808":20,"p980":25,"p1064":50},
  "pending_sync": false,
  "active": {"p808":true,"p980":true,"p1064":true}
}
```

If the controller rejects the write because the app is busy/not running, the requested values can be staged locally and `pending_sync` becomes true.

### `GET /laser/channel_pwr`

Reads channel power from the controller and returns backend logical power state.

Response fields:

- `response`: raw serial response.
- `power`: backend logical `p808`, `p980`, `p1064`.
- `raw_power`: parsed raw controller triplet when available.
- `pending_sync`: whether a staged write still needs retry.
- `active`: boolean channel state.

### `POST /laser/active`

Enables/disables active channels and optionally red dot.

Query parameters:

- `l1064` integer/bool, optional, default `1`.
- `l980` integer/bool, optional, default `1`.
- `l808` integer/bool, optional, default `1`.
- `l660` integer/bool, optional. When provided, updates red dot state.

Response:

```json
{
  "response": ["..."],
  "active": [true,true,true],
  "red_dot": false
}
```

Note: `active` is returned as `[l1064, l980, l808]`.

### `POST /laser/current`

Sets the same power/current value on all currently active 808/980/1064 channels.

Query parameters:

- `curr` integer, required. Clamped to `0..100`.

### `GET /laser/temp`

Returns parsed laser temperature from `SENSORS_GET_VALUES`.

```json
{"temp":32.5}
```

If the parsed response starts with `ERR:`, returns HTTP `500`.

### `GET /sensors/values`

Returns parsed sensor values and raw serial lines.

Response:

```json
{
  "values": {
    "inputCurrent_mA": 690.0,
    "laserTemp_C": 32.5
  },
  "raw": ["[SENSORS_GET_VALUES]->[...]"]
}
```

The exact sensor fields come from `code/serial_commands.py`.

### `POST /laser/pulse`

Sets target sequence laser pulse length.

Query parameters:

- `pulse_ms` integer, required. Clamped in `TargetInterface` to `10..1000`.

Response:

```json
{"response":["PULSE_MS=50"],"pulse_ms":50}
```

### `GET /laser/settings`

Returns combined arm, power, pulse, pending-sync, and target count state.

Response:

```json
{
  "response": {
    "arm": ["[LASER_GET_ARM_EN]->[1][12523]"],
    "power": ["[LASER_GET_CHANNEL_PWR]->[20,25,50][12523]"]
  },
  "armed": true,
  "power": {"p808":20,"p980":25,"p1064":50},
  "pulse_ms": 50,
  "pending_sync": false,
  "targets_count": 3
}
```

### `POST /laser/settings`

Updates arm state, channel powers, pulse length, and optionally reloads existing target points into the controller.

JSON body:

```json
{
  "armed": true,
  "p808": 20,
  "p980": 25,
  "p1064": 50,
  "pulse_ms": 50,
  "reload_targets": true
}
```

Response:

```json
{
  "response": {
    "power": ["..."],
    "pulse": ["PULSE_MS=50"],
    "targets": ["TARGET_COUNT=3"],
    "peltier": {"enabled":true},
    "arm": ["..."]
  },
  "armed": true,
  "power": {"p808":20,"p980":25,"p1064":50},
  "pulse_ms": 50,
  "pending_sync": false,
  "targets_reloaded": true,
  "targets_count": 3
}
```

When `armed` is false, the backend disarms before applying power/pulse settings. When `armed` is true, it arms after applying settings.

### `POST /laser/red_dot`

Sets red dot state.

Query parameters:

- `enabled` boolean, required.

### `POST /laser/red_dot_en`

Alias for setting red dot state.

### `GET /laser/red_dot_en`

Reads red dot state from the controller.

### `POST /laser/fire`

Fires the laser for a bounded duration.

Query parameters:

- `duration_ms` integer, required. Clamped to `10..1000`.

Response:

```json
{"response":["[LASER_FIRE][20]->[OK][12523]"],"duration_ms":20}
```

### `POST /laser/stop`

Stops laser firing immediately.

### `GET /laser/is_active`

Reads whether the laser pulse is active.

### `GET /laser/state`

Reads laser controller state.

## Application/Firmware Control

These endpoints use the laser serial interface to send `APP_*` firmware commands.

### `POST /startup/clean_state`

Puts the backend/UI runtime and microcontroller into a clean startup state:

- hair detection off
- live detection overlay off
- red dot off
- target sequence stopped/halted where possible
- target list cleared
- target error cleared
- laser stopped and disarmed
- app error cleared
- app and sequence event buffers cleared
- treatment runtime reset
- `APP_STATE` checked before and after cleanup

This endpoint is used by the treatment-only UI `CLEANUP STATES` button and by emergency stop.

## Treatment-Only App Endpoints

The simplified treatment UI uses these endpoints instead of the lower-level sequence controls. They are optimized to avoid expensive full state refreshes after fast actions.

### `GET /treatment/app/status`

Returns treatment mode/status, `APP_STATE`, target state/error, laser arm state, power/pulse, detection threshold/overlay state, loaded target count, and vacuum status. This endpoint performs multiple serial queries and should be called by button, not continuous polling.

### `POST /treatment/app/mode`

Query parameters:

- `mode`: `auto`, `semi_auto`, or `manual`.

Modes:

- `auto`: backend detects and fires automatically when vacuum is ON.
- `semi_auto`: two phases: `DETECT`, then `FIRE`.
- `manual`: two phases: `DETECT`, then repeated `NEXT`.

### `POST /treatment/app/detect`

Captures or reuses live cached detection results, converts detections to target coordinates, uploads targets to the controller, and returns target count plus compact treatment state.

Fast path: enable live detection first with `/detection/toggle?enabled=true`; then treatment detect can use the background inference cache.

### `POST /treatment/app/fire`

Starts the already-loaded target sequence for `semi_auto`. Requires vacuum ON, laser ARMED, target idle, target error clear, and nonzero laser power.

### `POST /treatment/app/next`

Manual-mode next target. Requires a prior manual `DETECT`.

### `POST /treatment/app/emergency_stop`

Target halt/stop, laser stop/disarm, vacuum off, then cleanup states.

### `POST /treatment/app/settings`

Query parameters:

- `p808`
- `p980`
- `p1064`
- `pulse_ms`

Sets treatment power/pulse. If targets are already loaded, the backend reloads them so target entries contain current power and pulse.

### `GET /app/state`

Reads overall firmware app state.

### `GET /app/last_error`

Reads last app-level error.

### `POST /app/clear_error`

Clears app-level error and resets backend red-dot state to false.

### `GET /app/errors`

Drains async serial messages, reads current app state and last error, and returns recent app error events.

Response:

```json
{
  "state": ["[APP_GET_STATE]->[RUNNING][12523]"],
  "last_error": ["[APP_GET_LAST_ERROR]->[No error][APP_ERROR_NONE][12523]"],
  "events": [
    {
      "level": "error",
      "message": "[APP_ERROR_HAPPENED]->[...]",
      "timestamp": 1710000000000
    }
  ]
}
```

Event `level` is `error` or `hard_fault`.

### `GET /app/errors/events`

Returns only buffered app error events.

### `POST /app/errors/clear`

Clears app error through firmware and clears the backend app-error event buffer.

### `POST /app/ping`

Sends `APP_PING`.

### `GET /app/commands`

Sends `APP_GET_COMMANDS`.

### `GET /app/command_catalog`

Returns local command metadata from `code/serial_commands.py`.

Response:

```json
{
  "commands": [
    {
      "name": "LASER_FIRE",
      "section": "LASER CONTROL",
      "parameters": "duration_ms",
      "description": "Fires laser for given pulse length...",
      "returns": "[LASER_FIRE][duration]->[OK][TS]",
      "returns_nok": "[LASER_FIRE][duration]->[NOK][reason][TS]",
      "example": "LASER_FIRE 20",
      "notes": ""
    }
  ]
}
```

### `GET /app/command_info`

Returns metadata for one local serial command.

Query parameters:

- `command` string, required. The first whitespace-separated token is used.

Responses:

- `200 {"command":"LASER_FIRE","meta":{...}}`
- `400 {"error":"Command is empty"}`
- `404 {"error":"Unknown command: ...","command":"..."}`

### `GET /app/limits`

Sends `APP_GET_LIMITS`.

### `POST /app/reset`

Sends `APP_RESET`.

### `GET /app/proc_time`

Sends `APP_GET_PROC_TIME`.

### `POST /app/laser_test/start`

Starts firmware laser power test with `APP_DO_LASER_PWR_TEST`.

### `GET /app/laser_test/result`

Reads `APP_GET_LASER_TEST_RESULT`.

### `GET /app/laser_test/data`

Reads `APP_GET_LASER_TEST_DATA`.

### `GET /app/test/status`

Drains async serial messages and returns app state, last error, laser test result, firmware/hardware version, processing time, and buffered test events.

Test event kinds:

- `watchdog`
- `laser_power_test`

Response:

```json
{
  "state": ["..."],
  "last_error": ["..."],
  "laser_test_result": ["..."],
  "fw_version": ["..."],
  "hw_version": ["..."],
  "proc_time": ["..."],
  "events": [
    {
      "kind": "laser_power_test",
      "status": "OK",
      "message": "[APP_LASER_PWR_TEST_FINISHED]->[OK]",
      "timestamp": 1710000000000
    }
  ]
}
```

### `GET /app/test/events`

Returns only buffered test events.

### `GET /app/fw_version`

Reads firmware version.

### `GET /app/hw_version`

Reads hardware version.

### `POST /app/raw_command`

Sends an operator-entered serial command string directly.

JSON body:

```json
{"command":"APP_GET_STATE"}
```

Response:

```json
{
  "command": "APP_GET_STATE",
  "response": ["[APP_GET_STATE]->[RUNNING][12523]"]
}
```

Returns `400` if `command` is empty.

## Target Sequence Control

The target sequence API stores a local target dictionary in `TargetInterface`, then can load it into firmware using `TARGET_SET_NEW_TARGET` commands. Target records are loaded as point-like line targets where `x0,y0` and `x1,y1` are the same coordinate, with current channel powers and configured pulse length.

The backend limits detected-point sequence updates to `_max_sequence_targets = 50`.

### `GET /seq/status`

Drains async serial messages and returns target controller status.

Response:

```json
{
  "state": ["[TARGET_GET_STATE]->[...]"],
  "mode": ["[TARGET_GET_MODE]->[...]"],
  "last_error": ["[TARGET_GET_LAST_ERROR]->[...]"],
  "target_count": 3,
  "show_target_points_overlay": false,
  "events": [
    {
      "status": "OK",
      "message": "[TARGET_SEQ_FINISHED]->[OK]",
      "timestamp": 1710000000000
    }
  ]
}
```

### `GET /seq/events`

Returns only buffered sequence events.

### `POST /seq/length`

Sets local sequence length and truncates local target storage if needed.

Query parameters:

- `length` integer, required. Clamped to `0..256`.

Response:

```json
{"response":["SEQ_LEN=10"],"length":10}
```

### `POST /seq/target`

Sets one local target point.

Query parameters:

- `idx` integer, required. Clamped to `0..255`.
- `x` integer, required. Clamped to `0..4095`.
- `y` integer, required. Clamped to `0..4095`.

Response:

```json
{"response":["TARGET[0]=2500,2600"],"idx":0,"x":2500,"y":2600}
```

### `POST /seq/show_targets`

Enables/disables target overlay drawing on the MJPEG stream. Enabled mode requires a loaded homography.

Query parameters:

- `enabled` boolean, required.

Response:

```json
{"show_target_points_overlay":true,"targets_count":3}
```

### `POST /seq/update_targets`

Builds sequence targets from the currently captured detection points, converts them from image to galvo coordinates, and loads them into the controller.

Response:

```json
{
  "response": ["SEQ_LEN=2","TARGET[0]=2871,3040","TARGET[1]=2910,3055","TARGET_COUNT=2"],
  "targets_count": 2,
  "detected_count": 2,
  "max_targets": 50,
  "truncated": false,
  "targets": [[2871,3040],[2910,3055]],
  "load_ms": 123.4
}
```

### `POST /seq/clear_targets`

Clears local target storage and sends `TARGET_CLEAR_TARGETS`.

Response:

```json
{"response":["[TARGET_CLEAR_TARGETS]->[OK][12523]"],"targets_count":0}
```

### `POST /seq/mode`

Sets target sequence mode.

Query parameters:

- `mode` string, required.

Accepted values:

- Manual mode: `manual`, `single`, `step`.
- Auto mode: `auto`, `all`.

Response:

```json
{"response":["[TARGET_SET_MODE][1]->[OK][12523]"],"mode":"AUTO"}
```

Unsupported values return `400`.

### `GET /seq/mode`

Reads target sequence mode from firmware.

### `POST /seq/start`

Starts the target sequence with `TARGET_START`.

Response:

```json
{"response":["[TARGET_START]->[OK][12523]"],"targets_count":3}
```

### `POST /seq/start_test`

Starts a test target sequence. Current implementation sends the same firmware command as `/seq/start`.

### `POST /seq/stop`

Stops active target sequence with `TARGET_STOP`.

### `POST /seq/halt`

Halts active target sequence with `TARGET_HALT`.

### `POST /seq/step`

Manual stepping helper.

Behavior:

- If the target state text contains `IDLE`, sets mode to manual and starts sequence.
- Otherwise resumes the active sequence with `TARGET_CONTINUE`.

Response:

```json
{
  "response": ["..."],
  "state": ["[TARGET_GET_STATE]->[...]"],
  "targets_count": 3
}
```

## Fire Sequence

### `POST /fire/walk`

Builds a sequence from captured detection points, orders them by nearest-neighbor path, loads them into the target controller, and starts the sequence.

Query parameters:

- `test_mode` boolean, optional, default `false`.

Response:

```json
{
  "status": "firing",
  "test_mode": false,
  "targets_count": 2,
  "response": {
    "load": ["TARGET_COUNT=2"],
    "start": ["[TARGET_START]->[OK][12523]"]
  }
}
```

Current implementation sends `TARGET_START` for both `test_mode=false` and `test_mode=true`.

## Typical Workflows

### Detect, Load Targets, Fire Test

```bash
curl -X POST "http://localhost:8000/detection/toggle?enabled=true"
curl -X POST "http://localhost:8000/detection/conf?conf=0.25"
curl -X POST "http://localhost:8000/detection/capture"
curl -X POST "http://localhost:8000/laser/settings" \
  -H "Content-Type: application/json" \
  -d '{"armed":false,"p808":20,"p980":25,"p1064":50,"pulse_ms":50,"reload_targets":false}'
curl -X POST "http://localhost:8000/seq/update_targets"
curl -X POST "http://localhost:8000/seq/start_test"
```

### Move To A Click In The Displayed Stream

```bash
curl -X POST "http://localhost:8000/mover/move_image?x=480&y=480"
```

### Arm And Fire A Single Pulse

```bash
curl -X POST "http://localhost:8000/laser/channel_pwr?p808=20&p980=25&p1064=50"
curl -X POST "http://localhost:8000/laser/arm"
curl -X POST "http://localhost:8000/laser/fire?duration_ms=20"
curl -X POST "http://localhost:8000/laser/stop"
curl -X POST "http://localhost:8000/laser/disarm"
```
