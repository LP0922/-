"""ESP32-S3 gateway driver for the LA10-D actuator Modbus RTU protocol."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable, Optional, Protocol


class SerialPort(Protocol):
    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


class LA10CommunicationError(RuntimeError):
    """The gateway did not return a complete, valid Modbus RTU response."""


class LA10ProtocolError(LA10CommunicationError):
    """The gateway response violated the documented Modbus RTU protocol."""


class LA10DeviceUnavailableError(LA10CommunicationError):
    """The configured consecutive communication failure limit was reached."""


class LA10FaultError(RuntimeError):
    """The actuator reports a fault and cannot safely start a motion."""


@dataclass(frozen=True)
class LA10Config:
    port: str
    slave_address: int = 1
    baudrate: int = 115200
    timeout_s: float = 0.3
    retries: int = 1
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.slave_address <= 247:
            raise ValueError("slave_address must be in the Modbus unicast range 1..247")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.retries < 0 or self.max_consecutive_failures < 1:
            raise ValueError("retry and failure limits must be non-negative/positive")


@dataclass(frozen=True)
class LA10Status:
    position_units: int
    target_units: int
    temperature_c: int
    current_ma: int
    fault_bits: int
    is_running: bool
    last_result: int

    @property
    def position_mm(self) -> float:
        return self.position_units / 200.0

    @property
    def target_mm(self) -> float:
        return self.target_units / 200.0

    @property
    def fault_names(self) -> tuple[str, ...]:
        faults = (
            (0x0001, "stall"),
            (0x0002, "over_temperature"),
            (0x0004, "over_current"),
            (0x0008, "motor_fault"),
        )
        return tuple(name for mask, name in faults if self.fault_bits & mask)


@dataclass(frozen=True)
class VibrationSettings:
    frequency_hz: int
    duty_permyriad: int
    enabled: bool


def modbus_crc16(payload: bytes) -> int:
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _append_crc(payload: bytes) -> bytes:
    return payload + modbus_crc16(payload).to_bytes(2, "little")


class LA10ModbusRTU:
    """Control the documented ESP32-S3 Modbus gateway, not the LA10 UART directly."""

    CONTROL_REGISTER = 0
    DIRECTION_REGISTER = 1
    DISTANCE_REGISTER = 2
    SPEED_REGISTER = 3
    EXECUTE_REGISTER = 4
    STATUS_START_REGISTER = 5
    STATUS_REGISTER_COUNT = 7
    VIBRATION_FREQUENCY_REGISTER = 12
    VIBRATION_DUTY_REGISTER = 13
    VIBRATION_ENABLE_REGISTER = 14
    MANUAL_WRITABLE_REGISTERS = frozenset((0, 1, 2, 3, 4, 12, 13, 14))

    READ_HOLDING_REGISTERS = 0x03
    WRITE_SINGLE_REGISTER = 0x06
    WRITE_MULTIPLE_REGISTERS = 0x10

    CONTROL_ENABLE = 1
    CONTROL_PAUSE = 2
    CONTROL_EMERGENCY_STOP = 3
    CONTROL_CLEAR_FAULT = 4

    def __init__(
        self,
        config: LA10Config,
        serial_port: Optional[SerialPort] = None,
        serial_factory: Optional[Callable[..., SerialPort]] = None,
    ) -> None:
        self.config = config
        self._serial = serial_port
        self._serial_factory = serial_factory
        self._consecutive_failures = 0

    @property
    def connected(self) -> bool:
        return self._serial is not None

    @property
    def healthy(self) -> bool:
        return self.connected and self._consecutive_failures < self.config.max_consecutive_failures

    def connect(self) -> None:
        if self._serial is not None:
            return
        factory = self._serial_factory or self._default_serial_factory
        self._serial = factory(
            port=self.config.port,
            baudrate=self.config.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self.config.timeout_s,
        )

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def enable(self) -> None:
        self._write_single(self.CONTROL_REGISTER, self.CONTROL_ENABLE)

    def pause(self) -> None:
        self._write_single(self.CONTROL_REGISTER, self.CONTROL_PAUSE)

    def emergency_stop(self) -> None:
        """Issue the documented emergency-stop command immediately."""
        self._write_single(self.CONTROL_REGISTER, self.CONTROL_EMERGENCY_STOP)

    def clear_fault(self) -> None:
        self._write_single(self.CONTROL_REGISTER, self.CONTROL_CLEAR_FAULT)

    def read_vibration_settings(self) -> VibrationSettings:
        """Read vibration frequency, duty cycle, and enable state from registers 12-14."""
        raw = self.read_holding_registers(self.VIBRATION_FREQUENCY_REGISTER, 3)
        values = [
            int.from_bytes(raw[index : index + 2], "big")
            for index in range(0, len(raw), 2)
        ]
        if values[2] not in (0, 1):
            raise LA10ProtocolError(f"LA10 vibration enable value is invalid: {values[2]}")
        return VibrationSettings(
            frequency_hz=values[0],
            duty_permyriad=values[1],
            enabled=values[2] == 1,
        )

    def start_vibration(self, *, frequency_hz: int, duty_permyriad: int) -> None:
        """Atomically set 10-80 Hz, 10%-50% duty, and enable vibration.

        ``duty_permyriad`` uses the gateway register scale: 1000 means 10% and
        5000 means 50%. The method returns once the gateway acknowledges the
        command; callers should record the command in the task RunRecord.
        """
        self._validate_vibration_settings(frequency_hz, duty_permyriad)
        # Register 14 only enables the vibration channel.  The gateway must
        # also be in its documented working state at register 0, especially
        # when no window move preceded the vibration command.
        self.enable()
        self._write_multiple(
            self.VIBRATION_FREQUENCY_REGISTER,
            [frequency_hz, duty_permyriad, 1],
        )

    def update_vibration_parameters(self, *, frequency_hz: int, duty_permyriad: int) -> None:
        """Atomically update registers 12-13 without changing enable register 14.

        Use this during continuous dispensing after :meth:`start_vibration`.
        It deliberately does not read or write the enable register, so a stage
        change cannot introduce a stop/start cycle that settles powder in the
        feeder path.
        """
        self._validate_vibration_settings(frequency_hz, duty_permyriad)
        self._write_multiple(
            self.VIBRATION_FREQUENCY_REGISTER,
            [frequency_hz, duty_permyriad],
        )

    def update_vibration_frequency(self, frequency_hz: int) -> None:
        """Update register 12 only; duty and enable remain unchanged."""
        if not isinstance(frequency_hz, int) or not 10 <= frequency_hz <= 80:
            raise ValueError("vibration frequency_hz must be an integer in the range 10..80")
        self._write_single(self.VIBRATION_FREQUENCY_REGISTER, frequency_hz)

    def update_vibration_duty(self, duty_permyriad: int) -> None:
        """Update register 13 only; frequency and enable remain unchanged."""
        if not isinstance(duty_permyriad, int) or not 1000 <= duty_permyriad <= 5000:
            raise ValueError("vibration duty_permyriad must be an integer in the range 1000..5000")
        self._write_single(self.VIBRATION_DUTY_REGISTER, duty_permyriad)

    def stop_vibration(self) -> None:
        """Immediately disable vibration while retaining the configured values."""
        self._write_single(self.VIBRATION_ENABLE_REGISTER, 0)

    def write_manual_register(self, register: int, value: int) -> None:
        """Write one documented operator-writable register.

        This is intended for the idle-device dashboard. Status registers remain
        read-only and the more restrictive vibration ranges are preserved.
        """
        if register not in self.MANUAL_WRITABLE_REGISTERS:
            raise ValueError(f"register {register} is read-only or unsupported for manual writes")
        if not isinstance(value, int):
            raise ValueError("manual register value must be an integer")
        if register == self.CONTROL_REGISTER and value not in (1, 2, 3, 4):
            raise ValueError("control register accepts documented commands 1..4")
        if register == self.DIRECTION_REGISTER and value not in (0, 1):
            raise ValueError("direction register accepts 0 or 1")
        if register == self.EXECUTE_REGISTER and value not in (0, 1):
            raise ValueError("execute register accepts 0 or 1")
        if register == self.VIBRATION_FREQUENCY_REGISTER and not 10 <= value <= 80:
            raise ValueError("vibration frequency must be in 10..80 Hz")
        if register == self.VIBRATION_DUTY_REGISTER and not 1000 <= value <= 5000:
            raise ValueError("vibration duty must be in 1000..5000")
        if register == self.VIBRATION_ENABLE_REGISTER and value not in (0, 1):
            raise ValueError("vibration enable register accepts 0 or 1")
        self._write_single(register, value)

    def read_status(self) -> LA10Status:
        raw = self.read_holding_registers(
            self.STATUS_START_REGISTER, self.STATUS_REGISTER_COUNT
        )
        values = [int.from_bytes(raw[index : index + 2], "big") for index in range(0, len(raw), 2)]
        return LA10Status(
            position_units=values[0],
            target_units=values[1],
            temperature_c=int.from_bytes(raw[4:6], "big", signed=True),
            current_ma=values[3],
            fault_bits=values[4],
            is_running=values[5] == 1,
            last_result=values[6],
        )

    def move_relative(
        self,
        *,
        extend: bool,
        distance_mm: float,
        speed_mm_s: float,
        check_fault: bool = True,
    ) -> None:
        """Submit one atomic relative-motion request to registers 1 through 4.

        Call :meth:`enable` first. The method returns after the gateway accepts
        the command; call :meth:`read_status` or :meth:`wait_until_stopped` to
        determine completion.
        """
        distance_units = self._to_hundredths(distance_mm, "distance_mm", 10.0)
        speed_units = self._to_hundredths(speed_mm_s, "speed_mm_s", 655.35)
        if check_fault:
            status = self.read_status()
            if status.fault_bits:
                faults = ", ".join(status.fault_names) or f"0x{status.fault_bits:04X}"
                raise LA10FaultError(f"LA10 actuator fault is active: {faults}")
        self._write_multiple(
            self.DIRECTION_REGISTER,
            [1 if extend else 0, distance_units, speed_units, 1],
        )

    def wait_until_stopped(
        self,
        *,
        timeout_s: float,
        poll_interval_s: float = 0.1,
        require_running_transition: bool = False,
    ) -> LA10Status:
        if timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("timeout_s and poll_interval_s must be positive")
        deadline = monotonic() + timeout_s
        saw_running = False
        while monotonic() < deadline:
            status = self.read_status()
            if status.fault_bits:
                faults = ", ".join(status.fault_names) or f"0x{status.fault_bits:04X}"
                raise LA10FaultError(f"LA10 actuator fault is active: {faults}")
            if status.is_running:
                saw_running = True
            elif not require_running_transition or saw_running:
                if status.last_result != 0:
                    raise LA10FaultError(f"LA10 motion failed with result {status.last_result}")
                return status
            sleep(poll_interval_s)
        transition_text = " after entering the running state" if require_running_transition else ""
        raise TimeoutError(f"LA10 motion did not stop{transition_text} before the configured timeout")

    def read_holding_registers(self, start_register: int, count: int) -> bytes:
        self._validate_register_range(start_register, count)
        request = _append_crc(
            bytes((self.config.slave_address, self.READ_HOLDING_REGISTERS))
            + start_register.to_bytes(2, "big")
            + count.to_bytes(2, "big")
        )
        response = self._transact(
            request, self.READ_HOLDING_REGISTERS, response_data_size=1 + count * 2
        )
        if response[0] != count * 2:
            raise LA10ProtocolError("LA10 response byte count does not match the read request")
        return response[1:]

    def _write_single(self, register: int, value: int) -> None:
        self._validate_register_range(register, 1)
        self._validate_register_value(value)
        request = _append_crc(
            bytes((self.config.slave_address, self.WRITE_SINGLE_REGISTER))
            + register.to_bytes(2, "big")
            + value.to_bytes(2, "big")
        )
        response = self._transact(request, self.WRITE_SINGLE_REGISTER, response_data_size=4)
        if response != request[2:6]:
            raise LA10ProtocolError("LA10 single-register response does not acknowledge the request")

    def _write_multiple(self, start_register: int, values: list[int]) -> None:
        self._validate_register_range(start_register, len(values))
        if not values:
            raise ValueError("at least one register value is required")
        for value in values:
            self._validate_register_value(value)
        payload = b"".join(value.to_bytes(2, "big") for value in values)
        request = _append_crc(
            bytes((self.config.slave_address, self.WRITE_MULTIPLE_REGISTERS))
            + start_register.to_bytes(2, "big")
            + len(values).to_bytes(2, "big")
            + bytes((len(payload),))
            + payload
        )
        response = self._transact(
            request, self.WRITE_MULTIPLE_REGISTERS, response_data_size=4
        )
        if response != request[2:6]:
            raise LA10ProtocolError("LA10 multi-register response does not acknowledge the request")

    def _transact(self, request: bytes, function_code: int, response_data_size: int) -> bytes:
        if self._consecutive_failures >= self.config.max_consecutive_failures:
            raise LA10DeviceUnavailableError("LA10 communication failure limit reached")
        last_error: Optional[LA10CommunicationError] = None
        for _ in range(self.config.retries + 1):
            try:
                response = self._exchange(request, function_code, response_data_size)
            except LA10CommunicationError as error:
                self._consecutive_failures += 1
                last_error = error
                if self._consecutive_failures >= self.config.max_consecutive_failures:
                    raise LA10DeviceUnavailableError("LA10 communication failure limit reached") from error
            else:
                self._consecutive_failures = 0
                return response
        assert last_error is not None
        raise last_error

    def _exchange(self, request: bytes, function_code: int, response_data_size: int) -> bytes:
        try:
            port = self._require_port()
            reset_input_buffer = getattr(port, "reset_input_buffer", None)
            if callable(reset_input_buffer):
                reset_input_buffer()
            port.write(request)
            port.flush()

            header = self._read_exactly(port, 2)
            address, received_function = header
            if address != self.config.slave_address:
                raise LA10ProtocolError("LA10 response address does not match configured address")
            if received_function == (function_code | 0x80):
                frame = header + self._read_exactly(port, 3)
                self._validate_crc(frame)
                raise LA10ProtocolError(f"LA10 Modbus exception code 0x{frame[2]:02X}")
            if received_function != function_code:
                raise LA10ProtocolError(f"LA10 returned function 0x{received_function:02X}")
            frame = header + self._read_exactly(port, response_data_size + 2)
            self._validate_crc(frame)
            return frame[2:-2]
        except OSError as error:
            raise LA10CommunicationError(
                f"LA10 serial I/O failed on {self.config.port}: {error}"
            ) from error

    @staticmethod
    def _read_exactly(port: SerialPort, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = port.read(remaining)
            if not chunk:
                raise LA10CommunicationError(f"LA10 response timed out with {remaining} bytes missing")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_crc(frame: bytes) -> None:
        expected = modbus_crc16(frame[:-2])
        received = int.from_bytes(frame[-2:], "little")
        if received != expected:
            raise LA10ProtocolError(
                f"LA10 CRC mismatch: got 0x{received:04X}, expected 0x{expected:04X}"
            )

    def _require_port(self) -> SerialPort:
        if self._serial is None:
            self.connect()
        assert self._serial is not None
        return self._serial

    @staticmethod
    def _validate_register_range(start_register: int, count: int) -> None:
        if count < 1 or start_register < 0 or start_register + count > 16:
            raise ValueError("LA10 register range must stay within documented addresses 0..15")

    @staticmethod
    def _validate_register_value(value: int) -> None:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("register values must be unsigned 16-bit integers")

    @staticmethod
    def _validate_vibration_settings(frequency_hz: int, duty_permyriad: int) -> None:
        if not isinstance(frequency_hz, int) or not 10 <= frequency_hz <= 80:
            raise ValueError("vibration frequency_hz must be an integer in the range 10..80")
        if not isinstance(duty_permyriad, int) or not 1000 <= duty_permyriad <= 5000:
            raise ValueError(
                "vibration duty_permyriad must be an integer in the range 1000..5000"
            )

    @staticmethod
    def _to_hundredths(value: float, name: str, maximum: float) -> int:
        if not 0 < value <= maximum:
            raise ValueError(f"{name} must be greater than 0 and no more than {maximum}")
        return round(value * 100)

    @staticmethod
    def _default_serial_factory(**kwargs: object) -> SerialPort:
        try:
            import serial
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("pyserial is required; install requirements.txt") from error
        return serial.Serial(**kwargs)
