# LaserDriver Tester GUI

Small Python/Tk desktop tool for exercising the LaserDriver USB CDC command interface.

## Run

Install the dependencies for the Python interpreter you will use:

```bat
python -m pip install -r requirements.txt
```

Then run:

```bat
python laser_driver_gui.py
```

or double-click `run_laser_driver_gui.bat`.

## Notes

- The firmware CDC baud value is line coding only; the real data path is USB. `115200` is kept as the default because the firmware and existing scripts use it.
- The camera preview uses OpenCV. On Windows, the GUI opens camera indexes through DirectShow; use the `Probe` button if the Arducam is not index `0`.
- Laser fire, target sequence start, and bootloader entry ask for confirmation in the GUI.
- `APP_BOOT ERASE` is intentionally destructive because it invalidates the firmware vector pages before entering the STM32 ROM bootloader.
