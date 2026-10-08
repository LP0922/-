"""AT8811C B/C-series Modbus RTU driver.

The device manual does not specify the raw-weight engineering unit. Set
``scale_mg_per_count`` from a certified reference-mass calibration before
using ``mass_mg`` for acceptance or ILC learning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol


class SerialPort(Protocol):
    """Minimal pyserial-compatible interface used by this driver."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


class CommunicationError(RuntimeError):
    """Raised when the serial transport does not provide a complete response."""


class ProtocolError(CommunicationError):
    """Raised when a response has an invalid Modbus address, function, or CRC."""


class DeviceUnavailableError(CommunicationError):
    """Raised after the configured consecutive communication failure limit."""


@dataclass(frozen=True)
class AT8811CConfig:
    port: str = "COM1"
    slave_address: int = 1
    baudrate: int = 9600
    timeout_s: float = 0.2
    retries: int = 1
    max_consecutive_failures: int = 3
    scale_mg_per_count: Optional[float] = None
    offset_mg: float = 0.0

    def __post_init__(self) -> None:
        if not 1 <= self.slave_address <= 247:
            raise ValueError("slave_address must be in the Modbus unicast range 1..247")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.retries < 0 or self.max_consecutive_failures < 1:
            raise ValueError("retry and failure limits must be non-negative/positive")
        if self.scale_mg_per_count is not None and self.scale_mg_per_count <= 0:
            raise ValueError("scale_mg_per_count must be positive when configured")


@dataclass(frozen=True)
class Measurement:
    raw_count: int
    mass_mg: Optional[float]
    stable: bool
    in_zero_band: bool
    status_word: int
    captured_at: datetime


def modbus_crc16(payload: bytes) -> int:
    """Return the Modbus CRC-16 value; RTU transmits its low byte first."""
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _append_crc(payload: bytes) -> bytes:
    return payload + modbus_crc16(payload).to_bytes(2, byteorder="little")


class AT8811CModbusRTU:
    """Driver for the AT8811C B/C-series RS-485 Modbus RTU interface.

    It supports read-only measurement use and an explicitly authorized zero
    command. Calibration, communication settings, and factory reset are not
    implemented because normal dispensing software must never change them.
    """

    WEIGHT_REGISTER = 0x0001
    STATUS_REGISTER = 0x0003
    READ_HOLDING_REGISTERS = 0x03
    WRITE_MULTIPLE_REGISTERS = 0x10

    def __init__(
        self,
        config: AT8811CConfig,
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

    def reset_connection(self) -> None:
        """Close the transport and clear a latched communication failure count."""
        self.close()
        self._consecutive_failures = 0

    def read_measurement(self) -> Measurement:
        """Read weight and status using the two RTU requests specified by AT8811C."""
        raw_count = self.read_raw_weight()
        status_word = self.read_status_word()
        mass_mg = None
        if self.config.scale_mg_per_count is not None:
            mass_mg = raw_count * self.config.scale_mg_per_count + self.config.offset_mg
        return Measurement(
            raw_count=raw_count,
            mass_mg=mass_mg,
            stable=bool(status_word & (1 << 8)),
            in_zero_band=bool(status_word & (1 << 9)),
            status_word=status_word,
            captured_at=datetime.now(timezone.utc),
        )

    def read_raw_weight(self) -> int:
        data = self._read_registers(self.WEIGHT_REGISTER, 2)
        return int.from_bytes(data, byteorder="big", signed=True)

    def read_status_word(self) -> int:
        data = self._read_registers(self.STATUS_REGISTER, 1)
        return int.from_bytes(data, byteorder="big", signed=False)

    def read_holding_registers(self, start_register: int, count: int) -> tuple[int, ...]:
        """Read raw 16-bit Modbus holding-register words for diagnostics.

        The method is intentionally read-only. Callers must interpret 32-bit
        values according to the device register map.
        """
        if not 0 <= start_register <= 0xFFFF:
            raise ValueError("start_register must be an unsigned 16-bit address")
        if not 1 <= count <= 125 or start_register + count > 0x10000:
            raise ValueError("count must be in the Modbus range 1..125")
        data = self._read_registers(start_register, count)
        return tuple(
            int.from_bytes(data[index : index + 2], byteorder="big", signed=False)
            for index in range(0, len(data), 2)
        )

    def zero(self, *, authorized: bool = False) -> None:
        """Clear the real-time weight register only after state-machine authorization.

        The caller must pass ``authorized=True`` exclusively from a verified TARE
        state with all dispensing actuators stopped.
        """
        if not authorized:
            raise PermissionError("zero requires explicit authorization from the TARE state")
        request = _append_crc(
            bytes((self.config.slave_address, self.WRITE_MULTIPLE_REGISTERS))
            + self.WEIGHT_REGISTER.to_bytes(2, "big")
            + (2).to_bytes(2, "big")
            + bytes((4, 0, 0, 0, 0))
        )
        response = self._transact(request, self.WRITE_MULTIPLE_REGISTERS, response_data_size=4)
        if response != request[2:6]:
            raise ProtocolError("AT8811C zero response does not acknowledge the requested registers")

    def _read_registers(self, start_register: int, count: int) -> bytes:
        request = _append_crc(
            bytes((self.config.slave_address, self.READ_HOLDING_REGISTERS))
            + start_register.to_bytes(2, "big")
            + count.to_bytes(2, "big")
        )
        response = self._transact(
            request,
            self.READ_HOLDING_REGISTERS,
            response_data_size=1 + count * 2,
        )
        byte_count = response[0]
        expected_count = count * 2
        if byte_count != expected_count:
            raise ProtocolError(
                f"AT8811C returned {byte_count} data bytes; expected {expected_count}"
            )
        return response[1:]

    def _transact(self, request: bytes, function_code: int, response_data_size: int) -> bytes:
        if self._consecutive_failures >= self.config.max_consecutive_failures:
            # A failed USB/RS-485 exchange must not permanently disable the
            # balance. Reopen the transport before the next caller retries.
            # The current transaction is never replayed implicitly here.
            self.reset_connection()
        last_error: Optional[CommunicationError] = None
        for _ in range(self.config.retries + 1):
            try:
                response = self._exchange(request, function_code, response_data_size)
            except CommunicationError as error:
                self._consecutive_failures += 1
                last_error = error
                if self._consecutive_failures >= self.config.max_consecutive_failures:
                    raise DeviceUnavailableError(
                        f"AT8811C communication failure limit reached: {error}"
                    ) from error
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

            header = self._read_exactly(port, 2, context="response header")
            address, received_function = header
            if address != self.config.slave_address:
                raise ProtocolError(f"AT8811C response address {address} does not match configured address")
            if received_function == (function_code | 0x80):
                exception_frame = header + self._read_exactly(
                    port,
                    3,
                    context="exception response body",
                )
                self._validate_crc(exception_frame)
                raise ProtocolError(f"AT8811C Modbus exception code 0x{exception_frame[2]:02X}")
            if received_function != function_code:
                raise ProtocolError(f"AT8811C returned function 0x{received_function:02X}")

            frame = header + self._read_exactly(
                port,
                response_data_size + 2,
                context="response body/CRC",
            )
            self._validate_crc(frame)
            return frame[2:-2]
        except OSError as error:
            raise CommunicationError(
                f"AT8811C serial I/O failed on {self.config.port}: {error}"
            ) from error

    @staticmethod
    def _read_exactly(port: SerialPort, size: int, *, context: str = "response") -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = port.read(remaining)
            if not chunk:
                received = b"".join(chunks)
                suffix = f"; received={received.hex(' ').upper()}" if received else ""
                raise CommunicationError(
                    f"AT8811C {context} timed out with {remaining} bytes missing{suffix}"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_crc(frame: bytes) -> None:
        expected_crc = modbus_crc16(frame[:-2])
        received_crc = int.from_bytes(frame[-2:], byteorder="little")
        if received_crc != expected_crc:
            raise ProtocolError(
                f"AT8811C CRC mismatch: got 0x{received_crc:04X}, expected 0x{expected_crc:04X}"
            )

    def _require_port(self) -> SerialPort:
        if self._serial is None:
            self.connect()
        assert self._serial is not None
        return self._serial

    @staticmethod
    def _default_serial_factory(**kwargs: object) -> SerialPort:
        try:
            import serial
        except ImportError as error:  # pragma: no cover - exercised by deployment setup
            raise RuntimeError("pyserial is required; install requirements.txt") from error
        return serial.Serial(**kwargs)
