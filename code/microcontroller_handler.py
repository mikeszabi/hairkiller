"""Own the single serial connection shared by all controller interfaces.

The function-specific interfaces can still create their own SerialDevice when
used as standalone command-line tools.  The backend should use this runtime so
there is exactly one port open, one reader thread, and one query lock.
"""

from __future__ import annotations

from typing import Optional

from galvo_handler import GalvoInterface
from laser_handler import LaserInterface
from serial_devices_handler import DEFAULT_BAUD, DEFAULT_PORT, SerialDevice
from target_handler import TargetInterface
from vacuum_handler import VacuumInterface


class MicrocontrollerInterface:
    """Connection owner and unified collection of functional interfaces."""

    def __init__(
        self,
        port: str = DEFAULT_PORT,
        baud: int = DEFAULT_BAUD,
        timeout_s: Optional[float] = None,
        debug: bool = False,
    ) -> None:
        kwargs = {}
        if timeout_s is not None:
            kwargs["timeout_s"] = timeout_s

        self.serial = SerialDevice(port=port, baud=baud, debug=debug, **kwargs)
        self.laser = None
        self.target = None
        self.vacuum = None
        self.galvo = None

        try:
            self.serial.open()
            self.laser = LaserInterface(dev=self.serial, debug=debug)
            self.target = TargetInterface(
                dev=self.serial,
                debug=debug,
                channel_provider=self.laser.get_channel_power_triplet,
            )
            self.vacuum = VacuumInterface(dev=self.serial, debug=debug)
            self.galvo = GalvoInterface(dev=self.serial, debug=debug)
        except Exception:
            self.serial.close()
            raise

    def close(self) -> None:
        """Close the shared connection after all interfaces stop using it."""
        self.serial.close()

