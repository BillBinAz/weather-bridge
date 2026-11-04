import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from stations.thermo_works import thermo_works
from stations.thermo_works.get_devices_for_user import Device, DeviceChannel, get_devices_for_user
from weather import data


class TestThermoWorks(unittest.TestCase):
    def setUp(self):
        self.environ_patch = patch.dict(os.environ, {}, clear=True)
        self.environ_patch.start()
        self.addCleanup(self.environ_patch.stop)
        self.devices_patch = patch(
            'stations.thermo_works.thermo_works.get_devices_for_user',
            new_callable=AsyncMock,
            return_value=([], {}),
        )
        self.get_devices = self.devices_patch.start()
        self.addCleanup(self.devices_patch.stop)
        self.home = data.Home()

    def test_check_types(self):
        for config, expected in (
            ("7|key|label", True), ("8|key|label", True),
            ("9|key|label", True), ("0|key|label", True),
            ("6|key|label", False), ("99|key|label", False),
            ("invalid", False), (None, False),
        ):
            with self.subTest(config=config):
                self.assertEqual(thermo_works.check_types(config), expected)

    def test_get_sensor_by_key(self):
        sensors = [MagicMock(key="device1"), MagicMock(key="device2")]
        self.assertIs(thermo_works.get_sensor_by_key(sensors, "device1"), sensors[0])
        self.assertIsNone(thermo_works.get_sensor_by_key(sensors, "missing"))
        self.assertIsNone(thermo_works.get_sensor_by_key([], "missing"))

    def test_no_sensors_does_not_request_devices(self):
        thermo_works.get_weather(self.home)
        self.get_devices.assert_not_called()
        self.assertEqual(self.home.climate.sensors, [])

    def test_all_sensor_types_keep_channel_mappings(self):
        os.environ.update({
            'CLIMATE_SENSOR_1': '7|node|freezer',
            'CLIMATE_SENSOR_2': '8|humidity|office',
            'CLIMATE_SENSOR_3': '9|two_probes|fridge',
        })
        self.get_devices.return_value = (
            [Device("node", "node"), Device("humidity", "humidity"),
             Device("two_probes", "two_probes")],
            {
                "node": [DeviceChannel(72.555), DeviceChannel(0)],
                "humidity": [DeviceChannel(70), DeviceChannel(55)],
                "two_probes": [DeviceChannel(72.5), DeviceChannel(38), DeviceChannel(-5)],
            },
        )
        thermo_works.get_weather(self.home)
        self.get_devices.assert_awaited_once()
        node, humidity, probes = self.home.climate.sensors
        self.assertEqual(node.temperature, 72.56)
        self.assertEqual(node.temperature_probe_0, 0)
        self.assertEqual(humidity.temperature, 70)
        self.assertEqual(humidity.humidity, 55)
        self.assertEqual(probes.temperature, 72.5)
        self.assertEqual(probes.temperature_probe_0, 38)
        self.assertEqual(probes.temperature_probe_1, -5)

    def test_serial_matches_when_device_id_differs(self):
        os.environ['CLIMATE_SENSOR_1'] = '7|M100311323|freezer'
        self.get_devices.return_value = (
            [Device("M100311323", "legacy_id")],
            {"M100311323": [DeviceChannel(72), DeviceChannel(0)]},
        )
        thermo_works.get_weather(self.home)
        self.assertEqual(len(self.home.climate.sensors), 1)
        self.assertEqual(self.home.climate.sensors[0].temperature_probe_0, 0)

    def test_v1_response_flows_into_configured_weather_sensors(self):
        os.environ.update({
            'CLIMATE_SENSOR_1': '7|M100311323|freezer',
            'CLIMATE_SENSOR_2': '8|humidity|office',
            'CLIMATE_SENSOR_3': '9|probes|fridge',
        })
        response = MagicMock(status=200)
        response.json = AsyncMock(return_value={"devices": [
            {"serial": "M100311323", "id": "device_id", "channels": [
                {"number": 2, "value": 0}, {"number": 1, "value": 72.5},
            ]},
            {"serial": "humidity", "displayUnits": "C", "channels": [
                {"number": 1, "value": 20}, {"number": 2, "value": 55, "units": "H"},
            ]},
            {"serial": "probes", "channels": [
                {"number": 3, "value": -5}, {"number": 1, "value": 70},
            ]},
        ]})
        with (
            patch.object(thermo_works, "get_devices_for_user", new=get_devices_for_user),
            patch(
                'stations.thermo_works.get_devices_for_user.connect.get_credentials',
                return_value=[MagicMock(label="password", value="twk_test_key")],
            ),
            patch('stations.thermo_works.get_devices_for_user.ClientSession') as session_class,
        ):
            session = session_class.return_value.__aenter__.return_value
            session.get = MagicMock()
            session.get.return_value.__aenter__.return_value = response
            thermo_works.get_weather(self.home)
            session.get.assert_called_once()
        node, humidity, probes = self.home.climate.sensors
        self.assertEqual(node.temperature, 72.5)
        self.assertEqual(node.temperature_probe_0, 0)
        self.assertEqual(humidity.temperature, 68)
        self.assertEqual(humidity.humidity, 55)
        self.assertEqual(probes.temperature, 70)
        self.assertEqual(probes.temperature_probe_0, data.DEFAULT_TEMPERATURE)
        self.assertEqual(probes.temperature_probe_1, -5)

    def test_celsius_temperatures_but_not_humidity_are_converted(self):
        os.environ.update({
            'CLIMATE_SENSOR_1': '8|humidity|office',
            'CLIMATE_SENSOR_2': '9|probes|fridge',
        })
        self.get_devices.return_value = (
            [Device("humidity", "humidity"), Device("probes", "probes")],
            {
                "humidity": [DeviceChannel(20, "C"), DeviceChannel(55, "C")],
                "probes": [DeviceChannel(20, "C"), DeviceChannel(0, "C"),
                           DeviceChannel(-18, "C")],
            },
        )
        thermo_works.get_weather(self.home)
        humidity, probes = self.home.climate.sensors
        self.assertEqual(humidity.temperature, 68)
        self.assertEqual(humidity.humidity, 55)
        self.assertEqual(probes.temperature_probe_0, 32)
        self.assertEqual(probes.temperature_probe_1, -0.4)

    def test_missing_values_and_probes_keep_defaults(self):
        os.environ['CLIMATE_SENSOR_1'] = '9|device|fridge'
        self.get_devices.return_value = (
            [Device("device", "device")],
            {"device": [DeviceChannel(None), DeviceChannel(38)]},
        )
        thermo_works.get_weather(self.home)
        sensor = self.home.climate.sensors[0]
        self.assertEqual(sensor.temperature, data.DEFAULT_TEMPERATURE)
        self.assertEqual(sensor.temperature_probe_0, 38)
        self.assertEqual(sensor.temperature_probe_1, data.DEFAULT_TEMPERATURE)

    def test_no_matching_sensor_or_missing_device_identifier(self):
        os.environ['CLIMATE_SENSOR_1'] = '7|configured|freezer'
        self.get_devices.return_value = (
            [Device("other", "other"), Device("", "")], {"other": []},
        )
        thermo_works.get_weather(self.home)
        self.assertEqual(self.home.climate.sensors, [])

    def test_continues_after_device_without_channels(self):
        os.environ.update({
            'CLIMATE_SENSOR_1': '7|bad|bad',
            'CLIMATE_SENSOR_2': '7|good|good',
        })
        self.get_devices.return_value = (
            [Device("bad", "bad"), Device("good", "good")],
            {"bad": [], "good": [DeviceChannel(72.5), DeviceChannel(0)]},
        )
        with self.assertLogs(thermo_works.logger, level="ERROR"):
            thermo_works.get_weather(self.home)
        self.assertEqual(len(self.home.climate.sensors), 1)
        self.assertEqual(self.home.climate.sensors[0].label, 'good')

    def test_event_loop_closes_on_success(self):
        os.environ['CLIMATE_SENSOR_1'] = '7|device|freezer'
        real_new_event_loop = thermo_works.asyncio.new_event_loop
        loop = real_new_event_loop()
        with patch.object(thermo_works.asyncio, "new_event_loop", return_value=loop):
            thermo_works.get_weather(self.home)
        self.assertTrue(loop.is_closed())

    def test_request_failure_is_logged_and_event_loop_closes(self):
        os.environ['CLIMATE_SENSOR_1'] = '7|device|freezer'
        self.get_devices.side_effect = RuntimeError("HTTP 401")
        loop = thermo_works.asyncio.new_event_loop()
        with (
            patch.object(thermo_works.asyncio, "new_event_loop", return_value=loop),
            patch.object(thermo_works.traceback, "print_exc"),
            patch('builtins.print'),
            self.assertLogs(level="ERROR") as logs,
        ):
            thermo_works.get_weather(self.home)
        self.assertIn("HTTP 401", logs.output[0])
        self.assertEqual(self.home.climate.sensors, [])
        self.assertTrue(loop.is_closed())


if __name__ == '__main__':
    unittest.main()
