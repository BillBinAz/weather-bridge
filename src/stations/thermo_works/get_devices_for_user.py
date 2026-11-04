import logging
import os
from dataclasses import dataclass

from aiohttp import ClientResponseError, ClientSession, ClientTimeout

import utilities.connect as connect

logger = logging.getLogger(__name__)
CONNECT_ITEM_ID = os.getenv("THERMOWORKS_CONNECT_ITEM_ID")
BASE_URL = "https://cloud.thermoworks.com/api/v1"


@dataclass
class Device:
    serial: str
    device_id: str


@dataclass
class DeviceChannel:
    value: float | None
    units: str | None = None


def _normalize_field_name(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _get_api_key(credentials) -> str:
    if not credentials:
        raise ValueError("Missing ThermoWorks credentials")

    password_field = next(
        (
            field for field in credentials
            if any(
                _normalize_field_name(getattr(field, name, None))
                in ("password", "pass", "passwd")
                for name in ("label", "title", "id", "purpose")
            )
        ),
        None,
    )
    # Older items expose the username and password only by position.
    if password_field is None and len(credentials) > 1:
        password_field = credentials[1]
    value = getattr(password_field, "value", None)
    key = str(value).strip() if value is not None else ""
    if not key:
        raise ValueError("Missing ThermoWorks API key in the 1Password password field")
    if not key.startswith("twk_") or len(key) <= 4 or any(ch.isspace() for ch in key):
        raise ValueError("ThermoWorks password field must contain a twk_ API key")
    return key


def _get_channels(raw_channels, device_units) -> list[DeviceChannel]:
    if not isinstance(raw_channels, (list, dict)):
        raise ValueError("ThermoWorks device channels must be an array or object")
    channels = {}
    entries = (
        raw_channels.items() if isinstance(raw_channels, dict)
        else enumerate(raw_channels, start=1)
    )
    for position, raw_channel in entries:
        if not isinstance(raw_channel, dict):
            raise ValueError("ThermoWorks channel must be an object")
        channel_number = int(raw_channel.get("number", position))
        if channel_number < 1 or channel_number in channels:
            raise ValueError("ThermoWorks channel numbers must be unique and positive")
        value = raw_channel.get("value")
        if value is not None:
            value = float(value)
        units = raw_channel.get("units") or device_units
        channels[channel_number] = DeviceChannel(value, units)

    # Keep gaps so a missing probe never shifts another reading into its slot.
    return [
        channels.get(number, DeviceChannel(None))
        for number in range(1, max(channels, default=0) + 1)
    ]


async def get_devices_for_user():
    api_key = _get_api_key(connect.get_credentials(CONNECT_ITEM_ID))
    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        async with session.get(
            f"{BASE_URL}/devices",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            allow_redirects=False,
        ) as response:
            try:
                response.raise_for_status()
            except ClientResponseError as error:
                raise RuntimeError(
                    f"ThermoWorks devices request failed (HTTP {error.status})"
                ) from None
            if response.status != 200:
                raise RuntimeError(
                    f"ThermoWorks devices request failed (HTTP {response.status})"
                )
            payload = await response.json()

    raw_devices = payload.get("devices") if isinstance(payload, dict) else payload
    if not isinstance(raw_devices, list):
        raise ValueError("ThermoWorks response must contain a devices array")

    devices = []
    device_channels_by_device = {}
    for raw_device in raw_devices:
        try:
            if not isinstance(raw_device, dict):
                raise ValueError("ThermoWorks device must be an object")
            serial = raw_device.get("serial") or raw_device.get("device_id") or raw_device.get("id")
            device_id = raw_device.get("device_id") or raw_device.get("id") or serial
            if not isinstance(serial, str) or not isinstance(device_id, str):
                raise ValueError("ThermoWorks device is missing its identifier")
            channels = _get_channels(
                raw_device.get("channels"), raw_device.get("displayUnits")
            )
            devices.append(Device(serial=serial, device_id=device_id))
            device_channels_by_device[serial] = channels
        except (ValueError, TypeError) as error:
            logger.error("Unable to read ThermoWorks device: %s", error)
    return devices, device_channels_by_device
