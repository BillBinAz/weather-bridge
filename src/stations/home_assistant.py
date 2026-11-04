#!/usr/bin/python3
import os
import traceback
from typing import Any
import requests
import logging

logger = logging.getLogger(__name__)
import json
from requests import Session

import utilities.connect as connect
import re

from utilities import conversions
from weather.data import AlarmZone, ALARM_ZONE_STATE_ERROR, ZONE_TYPE_DOOR, ZONE_TYPE_MOTION, ZONE_TYPE_GARAGE_DOOR, ZONE_TYPE_CONTACT, \
    CLIMATE_TYPE_ECOBEE_THERMOSTAT, CLIMATE_TYPE_ECOBEE_SENSOR, Door, DEFAULT_TEMPERATURE,ZONE_TYPE_BASIC,CLIMATE_TYPE_HUMIDITY, \
    CLIMATE_TYPE_SWITCH

CONNECT_ITEM_ID = os.getenv("HOME_ASSISTANT_CONNECT_ITEM_ID")
HOME_ASSISTANT_URL = os.getenv("HOME_ASSISTANT_URL")
TYPES_PROCESSED = [CLIMATE_TYPE_ECOBEE_THERMOSTAT, CLIMATE_TYPE_ECOBEE_SENSOR, ZONE_TYPE_DOOR,
                   ZONE_TYPE_MOTION, ZONE_TYPE_GARAGE_DOOR, ZONE_TYPE_CONTACT, ZONE_TYPE_BASIC, CLIMATE_TYPE_HUMIDITY,
                   CLIMATE_TYPE_SWITCH]

def get_bearer_token():
    try:
        # Get security data
        credentials = connect.get_credentials(CONNECT_ITEM_ID)
        return credentials[0].value

    except Exception as e:
        logging.error(f"Unable to get home-assistant:get_bearer_token {e}")


def get_sensor_data(bearer_token, key, s):
    url = HOME_ASSISTANT_URL + key
    try:
        ret = s.get(url, headers={"Accept": "application/json", "Authorization": "Bearer " + bearer_token})

        if ret.status_code != 200:
            logging.error(f"Bad response from home-assistant {ret.status_code}")
            raise Exception(f"Bad response from home-assistant {ret.status_code}")

        response = json.loads(ret.content.decode())
        if not response:
            raise Exception("No Data from home-assistant:SensorData.")

        return response

    except Exception as e:
        logging.error(f"Unable to get home-assistant:get_sensor_data Key: {key} {e}")


def get_value(bearer_token, key, s):
    sensor_data = get_sensor_data(bearer_token, key, s)
    if sensor_data is None:
        return 0
    return float(sensor_data["state"])


def get_occupancy(bearer_token, key, s):
    sensor_data = get_sensor_data(bearer_token, key, s)
    if sensor_data is None:
        return 0
    if sensor_data["state"] == "on":
        return 1
    else:
        return 0


def get_garage_door(bearer_token, key, s):
    sensor_data = get_sensor_data(bearer_token, key, s)
    if sensor_data is None:
        return 0
    if sensor_data["state"] == "off":
        return 1
    else:
        return 0


def get_on_off_state(bearer_token, key, s):
    sensor_data = get_sensor_data(bearer_token, key, s)
    if sensor_data is None:
        return ALARM_ZONE_STATE_ERROR
    if sensor_data["state"] == "off" or sensor_data["state"] == "Safe":
        return 1
    else:
        return 0

def get_locked_state(bearer_token, key, s):
    sensor_data = get_sensor_data(bearer_token, key, s)
    if sensor_data is None:
        return 0
    if sensor_data["state"] == "locked":
        return 1
    else:
        return 0

def get_alarm_label(bearer_token, key, s):
    sensor_data = get_sensor_data(bearer_token, key, s)
    if sensor_data is None:
        return "Disarmed"
    return sensor_data["state"].replace("_", " ").title()


def get_alarm_status(alarm_label):
    if alarm_label is None:
        return 0
    if alarm_label.lower() != "disarmed":
        return 1
    else:
        return 0

def populate_ecobee_sensor(bearer_token, climate_sensor, session):
    climate_sensor.temperature = get_value(bearer_token, "sensor." + climate_sensor.key + "_temperature", session)
    climate_sensor.occupied = get_occupancy(bearer_token, "binary_sensor." + climate_sensor.key + "_occupancy", session)

def populate_switch(bearer_token, climate_sensor, session):
    sensor_data = get_sensor_data(bearer_token, "switch." + climate_sensor.key, session)
    if sensor_data is not None:
        climate_sensor.state = sensor_data["state"]

def populate_ecobee_thermostat(bearer_token, climate_sensor, session):
    sensor_data = get_sensor_data(bearer_token, climate_sensor.key, session)

    if sensor_data is None:
        return

    climate_sensor.cool_set = sensor_data["attributes"]["target_temp_high"]
    climate_sensor.heat_set = sensor_data["attributes"]["target_temp_low"]
    climate_sensor.humidity = sensor_data["attributes"]["current_humidity"]
    climate_sensor.fan = sensor_data["attributes"]["fan_mode"][:10].title().strip()
    climate_sensor.temperature = float(sensor_data["attributes"]["current_temperature"])
    climate_sensor.dew_point = conversions.calculate_dew_point(
        climate_sensor.temperature,
        climate_sensor.humidity,
    )
    climate_sensor.state = sensor_data["attributes"]["hvac_action"][:10].title().strip()

    if sensor_data["state"] == "off":
        climate_sensor.mode = "Off"
    elif sensor_data["attributes"]["preset_mode"] == "temp":
        climate_sensor.mode = "Override"
    else:
        climate_sensor.mode = sensor_data["attributes"]["preset_mode"][:10].title().strip()

    key_result = climate_sensor.key.split('.')
    climate_sensor.occupied = get_occupancy(bearer_token, "binary_sensor." + key_result[1] + "_occupancy", session)


def add_climate_sensor(bearer_token: Any | None, config_data: str, home, temperature_sum, temperature_count, session: Session):
    climate_sensor = home.climate.create_sensor(config_data)

    if climate_sensor.type == CLIMATE_TYPE_HUMIDITY:
        sensor_data = get_sensor_data(bearer_token, "humidifier." + climate_sensor.key, session)
        climate_sensor.humidity = sensor_data["attributes"]["current_humidity"]
        climate_sensor.humidity_set = sensor_data["attributes"]["humidity"]
        if "mode" in sensor_data["attributes"]:
            climate_sensor.mode = sensor_data["attributes"]["mode"].title()
        elif "equipment_status" in sensor_data["attributes"]:
            climate_sensor.mode = sensor_data["attributes"]["equipment_status"].title()
        else:
            climate_sensor.mode = sensor_data["state"]
        return climate_sensor
    if climate_sensor.type == CLIMATE_TYPE_ECOBEE_THERMOSTAT:
        populate_ecobee_thermostat(bearer_token, climate_sensor, session)
        return climate_sensor
    if climate_sensor.type == CLIMATE_TYPE_ECOBEE_SENSOR:
        populate_ecobee_sensor(bearer_token, climate_sensor, session)
        return climate_sensor
    if climate_sensor.type == CLIMATE_TYPE_SWITCH:
        populate_switch(bearer_token, climate_sensor, session)
        return climate_sensor
    return None

def add_alarm_zone(bearer_token: Any | None, config_data: str, home,  s: Session):
    alarm_zone = AlarmZone(config_data)
    if alarm_zone.type == ZONE_TYPE_CONTACT:
        alarm_zone.closed = get_on_off_state(bearer_token, "binary_sensor." + alarm_zone.key, s)
        home.alarm.zones.append(alarm_zone)
    elif alarm_zone.type == ZONE_TYPE_MOTION:
        alarm_zone.closed = get_on_off_state(bearer_token, "binary_sensor." + alarm_zone.key, s)
        home.alarm.zones.append(alarm_zone)
    elif alarm_zone.type == ZONE_TYPE_GARAGE_DOOR:
        alarm_zone.closed = get_on_off_state(bearer_token, "binary_sensor." + alarm_zone.key, s)
        home.alarm.zones.append(alarm_zone)
    elif alarm_zone.type == ZONE_TYPE_DOOR:
        alarm_zone.closed = get_on_off_state(bearer_token, "binary_sensor." + alarm_zone.key, s)
        door = Door()
        door.locked = get_locked_state(bearer_token, "lock." + alarm_zone.door_key, s)
        alarm_zone.locked = door.locked
        door.label = alarm_zone.label
        home.doors.append(door)
        home.alarm.zones.append(alarm_zone)

    if alarm_zone.type == ZONE_TYPE_CONTACT and alarm_zone.closed == 0:
        home.alarm.all_zones_closed = 0

def check_types(config_data):
    try:
        result = config_data.split("|")
        type_id = int(result[0])
        return type_id == 0 or type_id in TYPES_PROCESSED
    except (ValueError, IndexError):
        return False


def get_weather(home, dt=None):
    session = requests.Session()
    alarm_present = False
    try:
        bearer_token = get_bearer_token()
        if not bearer_token:
            raise Exception("No BearerToken for home-assistant.")

        home.alarm.all_zones_closed = 1
        temperature_sum = 0
        temperature_count = 0

        for key, value in os.environ.items():
            config_data = os.getenv(key)
            try:
                if key.startswith("ALARM_ZONE") and check_types(config_data):
                    alarm_present = True
                    add_alarm_zone(bearer_token, config_data, home, session)
                if key.startswith("CLIMATE_SENSOR") and check_types(config_data):
                    climate_sensor = add_climate_sensor(
                        bearer_token,
                        config_data,
                        home,
                        temperature_sum,
                        temperature_count,
                        session,
                    )
                    if climate_sensor:
                        home.climate.sensors.append(climate_sensor)
                        if climate_sensor.type == CLIMATE_TYPE_ECOBEE_THERMOSTAT or climate_sensor.type == CLIMATE_TYPE_ECOBEE_SENSOR:
                            if climate_sensor.temperature is not DEFAULT_TEMPERATURE:
                                temperature_sum += float(climate_sensor.temperature)
                                temperature_count += 1
            except Exception as e:
                traceback.print_exc()
                logging.error(f"Unable to get home-assistant:get_weather item {key} {e}")
                print("Unable to get assistant:get_weather ")

        if temperature_count > 0:
            home.climate.home_average_temperature = conversions.format_f(temperature_sum / temperature_count, 1)

        if alarm_present:
            home.alarm.status_label = get_alarm_label(bearer_token, "alarm_control_panel.home_alarm", session)
            home.alarm.status_value = get_alarm_status(home.alarm.status_label)


    except Exception as e:
        traceback.print_exc()
        logging.error(f"Unable to get home-assistant:get_weather {e}")
        print("Unable to get assistant:get_weather ")
    finally:
        session.close()
