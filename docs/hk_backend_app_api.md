# hk_backend_app API Reference

`backend/hk_backend_app.py` is the consolidated HairKiller FastAPI backend. It replaces the previously separate full-app, calibration, and camera-test backend entrypoints while keeping the HTML frontends on the same request paths.

Run the production backend with:

```bash
uvicorn backend.hk_backend_app:app --host 0.0.0.0 --port 8000
```

Run the mock backend with:

```bash
uvicorn backend.hk_backend_mock_app:app --host 0.0.0.0 --port 8000
```

All API routes are available both at their direct path and under `/api/...`. The HTML frontends already default to `http://localhost:8000/api`.

## Frontend Coverage

- `app/hk_full_app.html` and `app/hk_full_app_portrait.html`
- `app/hk_calibration_app.html` and `app/hk_calibration_app_portrait.html`
- `app/hk_camera_test.html`

## Shared Diagnostics And Camera

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

`frame_stride` controls backend frame downsampling. The default is `2`, so a camera negotiated at 10 FPS is streamed and processed at about 5 FPS. The backend applies this same stride to live frontend streaming, background YOLO `split_inference`, and calibration red-dot detection.

## Full Application Workflow

The consolidated backend keeps the treatment, galvo, detector, sequence, laser, vacuum, firmware, and application diagnostics routes from the former full backend. These include:

- `/app/...`
- `/vacuum/...`
- `/seq/...`
- `/mover/...`
- `/detection/toggle`
- `/detection/conf`
- `/detection/capture`
- `/points/...`
- `/walk/...`
- `/laser/...`
- `/fire/walk`
- `/coords/convert`

The detailed route-by-route notes in `docs/hk_full_app_api.md` still describe this family of endpoints accurately.

## Calibration And Red-Dot Workflow

- `POST /calibration/detection/toggle?enabled=true|false`
- `POST /detection/mask_overlay?enabled=true|false`
- `GET /detection/status`
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

`/frame/current` is now shared: it can carry treatment overlays, target overlays, and calibration red-dot overlays without changing the frontend camera URL.

## Camera Test Workflow

The camera diagnostics page keeps its previous workflow:

- Read or apply camera controls through `/camera/settings`
- Refresh `/health`, `/stats`, and `/frame/meta`
- Fetch `/frame/snapshot`
- Run `/latency/benchmark`

The production backend reports live camera values. The mock backend returns stable synthetic values suitable for frontend work.

## Mock Backend Notes

`backend/hk_backend_mock_app.py` mirrors the merged route surface used by the HTML pages:

- `/api` prefix support is enabled.
- Calibration save/store and red-dot status are simulated.
- Camera settings, snapshots, and latency benchmark responses are simulated.
- Existing full-app mock behavior remains available for treatment workflow UI testing.
