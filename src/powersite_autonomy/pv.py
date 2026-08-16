# src/powersite_autonomy/pv.py
from __future__ import annotations

import math
from datetime import UTC

from .models import PVArrayConfig, SiteCalibration, SiteConfig, WeatherHour


def _local_hour(timestamp_hour: int, utc_offset_hours: float) -> int:
    return int((timestamp_hour + utc_offset_hours) % 24)


def _plane_of_array_irradiance(
    weather: WeatherHour,
    array: PVArrayConfig,
    *,
    latitude: float,
    longitude: float,
) -> float:
    """Estimate plane-of-array irradiance from GHI using compact solar geometry.

    This intentionally avoids a heavy solar-position dependency. It preserves the important
    orientation/tilt relationships while remaining deterministic and suitable for an edge box.
    """

    ghi = max(0.0, weather.shortwave_radiation_w_m2)
    if ghi <= 0:
        return 0.0

    timestamp = weather.timestamp.astimezone(UTC)
    day_of_year = timestamp.timetuple().tm_yday
    fractional_hour = timestamp.hour + timestamp.minute / 60 + timestamp.second / 3600

    declination = math.radians(23.45 * math.sin(math.radians(360 * (284 + day_of_year) / 365)))
    b = math.radians(360 * (day_of_year - 81) / 364)
    equation_of_time_minutes = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    solar_hour = fractional_hour + longitude / 15 + equation_of_time_minutes / 60
    hour_angle = math.radians(15 * (solar_hour - 12))

    latitude_r = math.radians(latitude)
    tilt = math.radians(array.tilt_deg)
    surface_azimuth = math.radians(array.azimuth_deg)

    sin_altitude = (
        math.sin(latitude_r) * math.sin(declination)
        + math.cos(latitude_r) * math.cos(declination) * math.cos(hour_angle)
    )
    if sin_altitude <= 0:
        return 0.0

    cos_incidence = (
        math.sin(declination) * math.sin(latitude_r) * math.cos(tilt)
        - math.sin(declination)
        * math.cos(latitude_r)
        * math.sin(tilt)
        * math.cos(surface_azimuth)
        + math.cos(declination)
        * math.cos(latitude_r)
        * math.cos(tilt)
        * math.cos(hour_angle)
        + math.cos(declination)
        * math.sin(latitude_r)
        * math.sin(tilt)
        * math.cos(surface_azimuth)
        * math.cos(hour_angle)
        + math.cos(declination)
        * math.sin(tilt)
        * math.sin(surface_azimuth)
        * math.sin(hour_angle)
    )
    beam_ratio = max(0.0, cos_incidence) / max(0.08, sin_altitude)
    beam_ratio = min(2.5, beam_ratio)

    cloud_fraction = (weather.cloud_cover_percent or 0.0) / 100.0
    diffuse_fraction = min(0.85, max(0.15, 0.22 + 0.55 * cloud_fraction))
    sky_view = (1 + math.cos(tilt)) / 2
    ground_view = (1 - math.cos(tilt)) / 2
    poa = ghi * ((1 - diffuse_fraction) * beam_ratio + diffuse_fraction * sky_view)
    poa += ghi * array.ground_albedo * ground_view
    return max(0.0, min(1_600.0, poa))


def estimate_array_power_w(
    weather: WeatherHour,
    array: PVArrayConfig,
    *,
    latitude: float,
    longitude: float,
    local_hour: int,
) -> float:
    poa = _plane_of_array_irradiance(
        weather,
        array,
        latitude=latitude,
        longitude=longitude,
    )
    ambient_c = weather.temperature_c if weather.temperature_c is not None else 25.0
    cell_temperature_c = ambient_c + (poa / 800.0) * (array.noct_c - 20.0)
    temperature_factor = max(
        0.50,
        min(1.20, 1 + array.temperature_coefficient_per_c * (cell_temperature_c - 25.0)),
    )
    shading_factor = array.shading_by_hour[local_hour]
    power = (
        array.rated_watts
        * (poa / 1000.0)
        * array.performance_ratio
        * (1 - array.wiring_loss_fraction)
        * array.controller_efficiency
        * temperature_factor
        * shading_factor
    )
    if array.controller_max_power_w is not None:
        power = min(power, array.controller_max_power_w)
    return max(0.0, power)


def estimate_site_pv_power_w(
    weather: WeatherHour,
    site: SiteConfig,
    calibration: SiteCalibration | None = None,
) -> float:
    local_hour = _local_hour(weather.timestamp.hour, site.utc_offset_hours)
    power = sum(
        estimate_array_power_w(
            weather,
            array,
            latitude=site.latitude,
            longitude=site.longitude,
            local_hour=local_hour,
        )
        for array in site.resolved_pv_arrays()
    )
    if calibration is not None:
        scale = calibration.pv_scale_factor * calibration.pv_scale_by_hour[local_hour]
        power *= max(0.2, min(2.0, scale))
    return max(0.0, power)
