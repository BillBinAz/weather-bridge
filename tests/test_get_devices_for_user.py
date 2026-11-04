import os
import sys
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientResponseError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from stations.thermo_works import get_devices_for_user


class TestGetDevicesForUser(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.credentials_patch = patch(
            'stations.thermo_works.get_devices_for_user.connect.get_credentials',
            return_value=[
                SimpleNamespace(label="username", value="unused"),
                SimpleNamespace(label="password", value=" twk_test_key "),
            ],
        )
        self.credentials = self.credentials_patch.start()
        self.addCleanup(self.credentials_patch.stop)
        self.session_patch = patch(
            'stations.thermo_works.get_devices_for_user.ClientSession'
        )
        self.session_class = self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.session = MagicMock()
        self.session_class.return_value.__aenter__.return_value = self.session
        self.response = MagicMock(status=200)
        self.response.json = AsyncMock(return_value={"devices": []})
        self.session.get.return_value.__aenter__.return_value = self.response

    async def test_bearer_key_from_same_item_password(self):
        result = await get_devices_for_user.get_devices_for_user()

        self.assertEqual(result, ([], {}))
        self.credentials.assert_called_once_with(get_devices_for_user.CONNECT_ITEM_ID)
        self.session.get.assert_called_once_with(
            'https://cloud.thermoworks.com/api/v1/devices',
            headers={
                "Authorization": "Bearer twk_test_key",
                "Accept": "application/json",
            },
            allow_redirects=False,
        )
        self.response.raise_for_status.assert_called_once()
        self.assertEqual(self.session_class.call_args.kwargs["timeout"].total, 30)
        self.session_class.return_value.__aexit__.assert_awaited_once()

    async def test_password_purpose_with_reordered_fields(self):
        self.credentials.return_value = [
            SimpleNamespace(label="Cloud key", purpose="PASSWORD", value="twk_correct"),
            SimpleNamespace(label="username", value="unused"),
        ]
        await get_devices_for_user.get_devices_for_user()
        self.assertEqual(
            self.session.get.call_args.kwargs["headers"]["Authorization"],
            "Bearer twk_correct",
        )

    async def test_legacy_positional_password(self):
        self.credentials.return_value = [
            SimpleNamespace(value="unused"), SimpleNamespace(value="twk_positional")
        ]
        await get_devices_for_user.get_devices_for_user()
        self.assertEqual(
            self.session.get.call_args.kwargs["headers"]["Authorization"],
            "Bearer twk_positional",
        )

    async def test_missing_or_invalid_password_is_rejected_before_request(self):
        for credentials in (
            None, [], [SimpleNamespace(label="username", value="unused")],
            [SimpleNamespace(label="password", value="")],
            [SimpleNamespace(label="password", value="old_login_password")],
            [SimpleNamespace(label="password", value="twk_")],
            [SimpleNamespace(label="password", value="twk_bad\nkey")],
        ):
            with self.subTest(credentials=credentials):
                self.credentials.return_value = credentials
                with self.assertRaises(ValueError):
                    await get_devices_for_user.get_devices_for_user()
        self.session_class.assert_not_called()

    async def test_devices_and_all_channels(self):
        self.response.json.return_value = {"generatedAt": "2026-11-03T00:00:00Z", "devices": [
            {"id": "device_id", "serial": "M100311323", "channels": [
                {"number": 2, "value": 0.0},
                {"number": 1, "value": 72.5},
                {"number": 3, "value": None},
            ]},
            {"serial": "other_serial", "channels": [
                {"value": 70}, {"value": 50},
            ]},
        ]}
        devices, channels = await get_devices_for_user.get_devices_for_user()
        self.assertEqual(devices[0].device_id, "device_id")
        self.assertEqual(devices[0].serial, "M100311323")
        self.assertEqual(devices[1].device_id, "other_serial")
        self.assertEqual(
            [channel.value for channel in channels["M100311323"]],
            [72.5, 0.0, None],
        )
        self.assertEqual(len(channels["other_serial"]), 2)
        self.session.get.assert_called_once()

    async def test_bare_devices_array_and_serial_fallback(self):
        self.response.json.return_value = [
            {"id": "M100311323", "channels": [{"value": 72.5}]},
        ]
        devices, channels = await get_devices_for_user.get_devices_for_user()
        self.assertEqual(devices[0].device_id, "M100311323")
        self.assertEqual(channels["M100311323"][0].value, 72.5)

    async def test_v1_fixture(self):
        fixture_path = os.path.join(
            os.path.dirname(__file__), "resources", "thermoworks_devices_data.json"
        )
        with open(fixture_path, encoding="utf-8") as fixture:
            self.response.json.return_value = json.load(fixture)
        devices, channels = await get_devices_for_user.get_devices_for_user()
        self.assertEqual(devices[0].device_id, "test-node")
        self.assertEqual(devices[0].serial, "test-node-serial")
        self.assertEqual(
            [(channel.value, channel.units) for channel in channels["test-node-serial"]],
            [(72.5, "F"), (55.0, "H")],
        )

    async def test_channel_gaps_and_units(self):
        self.response.json.return_value = {"devices": [
            {"serial": "device", "displayUnits": "C", "channels": [
                {"number": 3, "value": 0, "units": "C"},
                {"number": 1, "value": 20},
                {"number": 4, "value": 50, "units": "H"},
            ]},
        ]}
        _, channels = await get_devices_for_user.get_devices_for_user()
        self.assertEqual(
            [channel.value for channel in channels["device"]],
            [20.0, None, 0.0, 50.0],
        )
        self.assertEqual(channels["device"][0].units, "C")
        self.assertEqual(channels["device"][3].units, "H")

    async def test_invalid_channel_numbers_are_logged(self):
        for numbers in ((0,), (-1,), (1, 1), (None,), ("invalid",)):
            with self.subTest(numbers=numbers):
                self.response.json.return_value = {"devices": [
                    {"serial": "bad", "channels": [
                        {"number": number, "value": 72} for number in numbers
                    ]},
                ]}
                with self.assertLogs(get_devices_for_user.logger, level="ERROR"):
                    result = await get_devices_for_user.get_devices_for_user()
                self.assertEqual(result, ([], {}))

    async def test_http_errors_are_explicit_and_do_not_expose_key(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.response.raise_for_status.side_effect = ClientResponseError(
                    MagicMock(), (), status=status, message="Request failed"
                )
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}") as caught:
                    await get_devices_for_user.get_devices_for_user()
                self.assertNotIn("twk_test_key", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
        self.response.json.assert_not_awaited()

    async def test_redirect_is_not_treated_as_success(self):
        self.response.status = 302
        with self.assertRaisesRegex(RuntimeError, "HTTP 302"):
            await get_devices_for_user.get_devices_for_user()
        self.response.json.assert_not_awaited()

    async def test_invalid_response_and_json_error_propagate(self):
        for payload in (None, {}, {"devices": {}}, "not devices"):
            with self.subTest(payload=payload):
                self.response.json.return_value = payload
                with self.assertRaisesRegex(ValueError, "devices array"):
                    await get_devices_for_user.get_devices_for_user()
        self.response.json.side_effect = ValueError("Invalid JSON")
        with self.assertRaisesRegex(ValueError, "Invalid JSON"):
            await get_devices_for_user.get_devices_for_user()

    async def test_timeout_propagates_and_session_closes(self):
        self.session.get.return_value.__aenter__.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await get_devices_for_user.get_devices_for_user()
        self.session_class.return_value.__aexit__.assert_awaited_once()

    async def test_bad_device_is_logged_without_dropping_good_device(self):
        self.response.json.return_value = {"devices": [
            {"serial": "bad", "channels": [{"number": 0, "value": 1}]},
            {"channels": []},
            {"serial": "good", "channels": [{"value": 72}]},
        ]}
        with self.assertLogs(get_devices_for_user.logger, level="ERROR") as logs:
            devices, channels = await get_devices_for_user.get_devices_for_user()
        self.assertEqual(len(logs.output), 2)
        self.assertEqual([device.serial for device in devices], ["good"])
        self.assertEqual(channels["good"][0].value, 72)


if __name__ == '__main__':
    unittest.main()
