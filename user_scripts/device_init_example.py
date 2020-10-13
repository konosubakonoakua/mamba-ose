# Beamline devices initialization script.
# =========================================
# A dictionary __registered_devices should be defined in this file.
# It is of the type: Dict[DeviceType, Dict[str, Any]]
# The _Any_ here is actually the device object. It can be a ophyd object,
# or other objects providing similar interface as an ohpyd.

from typing import Dict, Any

from . import DeviceType

__registered_devices: Dict[DeviceType, Dict[str, Any]]

print("Initializing devices...")

from ophyd.sim import motor1, motor2, det, direct_img

motors = {
    'mSampleX': motor1,
    'mSampleZ': motor2,
}

dets = {
    'det': det,
    'direct_img': direct_img,
}

__registered_devices = {
    DeviceType.Motor: motors,
    DeviceType.Detector: dets
}
