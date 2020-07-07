#  NanoVNASaver
#
#  A python program to view and export Touchstone data from a NanoVNA
#  Copyright (C) 2019, 2020  Rune B. Broberg
#  Copyright (C) 2020 NanoVNA-Saver Authors
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
import logging
import struct
from time import sleep, time
from typing import List

import serial
import numpy as np
from PyQt5 import QtGui

from NanoVNASaver.Hardware.Serial import drain_serial, Interface
from NanoVNASaver.Hardware.VNA import VNA, Version

logger = logging.getLogger(__name__)


class NanoVNA(VNA):
    name = "NanoVNA"
    screenwidth = 320
    screenheight = 240

    def __init__(self, iface: Interface):
        super().__init__(iface)
        version_string = self.readVersion()
        self.version = Version(version_string)
        self.sweep_method = "sweep"
        self.start = 27000000
        self.stop = 30000000
        self._sweepdata = []

    def _capture_data(self) -> bytes:
        timeout = self.serial.timeout
        with self.serial.lock:
            drain_serial(self.serial)
            timeout = self.serial.timeout
            self.serial.write("capture\r".encode('ascii'))
            self.serial.readline()
            self.serial.timeout = 4
            image_data = self.serial.read(
                self.screenwidth * self.screenheight * 2)
            self.serial.timeout = timeout
        self.serial.timeout = timeout
        rgb_data = struct.unpack(
            f">{self.screenwidth * self.screenheight}H",
            image_data)
        rgb_array = np.array(rgb_data, dtype=np.uint32)
        return (0xFF000000 +
                ((rgb_array & 0xF800) << 8) +
                ((rgb_array & 0x07E0) << 5) +
                ((rgb_array & 0x001F) << 3))

    def getScreenshot(self) -> QtGui.QPixmap:
        logger.debug("Capturing screenshot...")
        if not self.connected():
            return QtGui.QPixmap()
        try:
            rgba_array = self._capture_data()
            image = QtGui.QImage(
                rgba_array,
                self.screenwidth,
                self.screenheight,
                QtGui.QImage.Format_ARGB32)
            logger.debug("Captured screenshot")
            return QtGui.QPixmap(image)
        except serial.SerialException as exc:
            logger.exception(
                "Exception while capturing screenshot: %s", exc)
        return QtGui.QPixmap()

    def resetSweep(self, start: int, stop: int):
        list(self.exec_command(f"sweep {start} {stop} {self.datapoints}"))
        list(self.exec_command("resume"))

    def setSweep(self, start, stop):
        self.start = start
        self.stop = stop
        if self.sweep_method == "sweep":
            list(self.exec_command(f"sweep {start} {stop} {self.datapoints}"))
        elif self.sweep_method == "scan":
            list(self.exec_command(f"scan {start} {stop} {self.datapoints}"))

    def read_features(self):
        if self.version >= Version("0.7.1"):
            self.features.add("Scan mask command")
            self.sweep_method = "scan_mask"
        elif self.version >= Version("0.2.0"):
            logger.debug("Newer than 0.2.0, using new scan command.")
            self.features.add("Scan command")
            self.sweep_method = "scan"
        super().read_features()

    def readFrequencies(self) -> List[int]:
        if self.sweep_method != "scan_mask":
            return super().readFrequencies()
        step = (self.stop - self.start) / (self.datapoints - 1.0)
        return [round(self.start + i * step) for i in range(self.datapoints)]

    def readValues(self, value) -> List[str]:
        if self.sweep_method != "scan_mask":
            return super().readValues(value)
        logger.debug("readValue with scan mask (%s)", value)
        # Actually grab the data only when requesting channel 0.
        # The hardware will return all channels which we will store.
        if value == "data 0":
            self._sweepdata = []
            for line in self.exec_command(
                    f"scan {self.start} {self.stop} {self.datapoints} 0b110"):
                data = line.split()
                self._sweepdata.append((
                    f"{data[0]} {data[1]}",
                    f"{data[2]} {data[3]}"))
        if value == "data 0":
            return [x[0] for x in self._sweepdata]
        if value == "data 1":
            return [x[1] for x in self._sweepdata]
