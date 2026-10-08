# Device Adapters

Balance, motion controller, vibration feeder, gate, ionizer, sensors, and safety interlocks.

- `at8811c_modbus_rtu.py`: AT8811C balance, default `9600/8-N-1`.
- `la10_modbus_rtu.py`: ESP32-S3 gateway for an LA10-D actuator, default
  `115200/8-N-1`.

The two devices use different default baud rates and must use separate serial
ports unless their firmware and physical bus configuration are deliberately
changed.
