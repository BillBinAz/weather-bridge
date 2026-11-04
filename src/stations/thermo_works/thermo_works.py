#!/usr/bin/python3
import asyncio
import datetime as dt
import logging
logger = logging.getLogger(__name__)
import os
import traceback
from stations.thermo_works.get_devices_for_user import get_devices_for_user
import utilities.conversions as conversions
from weather.data import CLIMATE_TYPE_THERMOWORKS_NODE, CLIMATE_TYPE_THERMOWORKS_NODE_WITH_HUMIDITY, CLIMATE_TYPE_THERMOWORKS_NODE_TWO_CHANNEL

TYPES_PROCESSED = [CLIMATE_TYPE_THERMOWORKS_NODE, CLIMATE_TYPE_THERMOWORKS_NODE_WITH_HUMIDITY, CLIMATE_TYPE_THERMOWORKS_NODE_TWO_CHANNEL]

def check_types(config_data):
    try:
        result = config_data.split("|")
        type_id = int(result[0])
        if type_id and type_id in TYPES_PROCESSED:
            return True
        if type_id == 0:
            return True

        return False
    except (ValueError, IndexError, AttributeError):
        return False

def get_sensor_by_key(sensors, key):
    for sensor in sensors:
        if sensor.key == key:
            return sensor
    return None

def get_weather(home):
    try:
        # get list of objects we care about
        sensors = []

        for key, value in os.environ.items():
            config_data = os.getenv(key)
            if key.startswith("CLIMATE_SENSOR") and check_types(config_data):
                sensors.append(home.climate.create_sensor(config_data))
        if len(sensors) == 0:
            return

        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(get_devices_for_user())
            loop.run_until_complete(task)
            results = task.result()
        finally:
            loop.close()
        devices = results[0]
        device_channels_by_device = results[1]

        for device in devices:
            try:
                if not device.serial:
                    continue

                device_channels = device_channels_by_device.get(device.serial, [])

                if not device.device_id:
                    continue

                sensor = get_sensor_by_key(sensors, device.device_id)
                if sensor is None:
                    sensor = get_sensor_by_key(sensors, device.serial)
                if sensor is not None:
                    if sensor.type == CLIMATE_TYPE_THERMOWORKS_NODE_WITH_HUMIDITY:
                        fields = ("temperature", "humidity")
                    elif sensor.type == CLIMATE_TYPE_THERMOWORKS_NODE_TWO_CHANNEL:
                        fields = ("temperature", "temperature_probe_0", "temperature_probe_1")
                    elif sensor.type == CLIMATE_TYPE_THERMOWORKS_NODE:
                        fields = ("temperature", "temperature_probe_0")
                    else:
                        continue
                    if not device_channels:
                        logger.error("ThermoWorks device %s has no channels", device.serial)
                        continue
                    for field, channel in zip(fields, device_channels):
                        if channel.value is not None:
                            value = channel.value
                            if field != "humidity" and channel.units == "C":
                                value = conversions.c_to_f_raw(value)
                            setattr(sensor, field, conversions.format_f(value))
                    home.climate.sensors.append(sensor)
            except Exception as e:
                traceback.print_exc()
                logging.error(f"Unable to get thermo_works:device {device.serial} {e}")
                print(dt.datetime.now().time(), f"Unable to get thermo_works:get_weather {e}")

    except Exception as e:
        traceback.print_exc()
        logging.error(f"Unable to get thermo_works:get_weather {e}")
        print(dt.datetime.now().time(), f"Unable to get thermo_works:get_weather {e}")
    return