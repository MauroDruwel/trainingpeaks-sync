"""
TCX generation from Strava streams data.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional


SPORT_MAPPING = {
    "Run": "Running",
    "Ride": "Biking",
    "Swim": "Other",
    "Walk": "Running",
    "Hike": "Running",
    "VirtualRide": "Biking",
    "VirtualRun": "Running",
    "EBikeRide": "Biking",
    "GravelRide": "Biking",
    "MountainBikeRide": "Biking",
    "TrailRun": "Running",
}


def build_trackpoint(trackpoint_index: int, start_time: datetime, streams: Dict[str, Any]) -> str:
    """Build a TCX Trackpoint XML element from Strava streams data."""
    point_time = start_time + timedelta(seconds=streams["time"][trackpoint_index])
    trackpoint_element = '        <Trackpoint>\n'
    trackpoint_element += f'          <Time>{point_time.strftime("%Y-%m-%dT%H:%M:%SZ")}</Time>\n'

    latlng_stream = streams.get("latlng", [])
    if trackpoint_index < len(latlng_stream) and latlng_stream[trackpoint_index]:
        lat, lng = latlng_stream[trackpoint_index]
        trackpoint_element += '          <Position>\n'
        trackpoint_element += f'            <LatitudeDegrees>{lat}</LatitudeDegrees>\n'
        trackpoint_element += f'            <LongitudeDegrees>{lng}</LongitudeDegrees>\n'
        trackpoint_element += '          </Position>\n'

    altitude_stream = streams.get("altitude", [])
    if trackpoint_index < len(altitude_stream):
        trackpoint_element += f'          <AltitudeMeters>{altitude_stream[trackpoint_index]}</AltitudeMeters>\n'

    distance_stream = streams.get("distance", [])
    if trackpoint_index < len(distance_stream):
        trackpoint_element += f'          <DistanceMeters>{distance_stream[trackpoint_index]}</DistanceMeters>\n'

    heartrate_stream = streams.get("heartrate", [])
    if trackpoint_index < len(heartrate_stream):
        trackpoint_element += '          <HeartRateBpm>\n'
        trackpoint_element += f'            <Value>{heartrate_stream[trackpoint_index]}</Value>\n'
        trackpoint_element += '          </HeartRateBpm>\n'

    cadence_stream = streams.get("cadence", [])
    if trackpoint_index < len(cadence_stream):
        trackpoint_element += f'          <Cadence>{cadence_stream[trackpoint_index]}</Cadence>\n'

    trackpoint_element += '        </Trackpoint>\n'
    return trackpoint_element


def generate_tcx_from_streams(activity: Dict[str, Any], streams: Dict[str, Any]) -> Optional[str]:
    """Generate valid TCX XML content from Strava activity and streams data."""
    activity_type = activity.get("type", "Other")
    sport = SPORT_MAPPING.get(activity_type, "Other")

    start_time_str = activity.get("start_date", datetime.now(timezone.utc).isoformat())
    try:
        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
    except ValueError:
        start_time = datetime.now(timezone.utc)

    time_stream = streams.get("time", {}).get("data", [])
    distance_stream = streams.get("distance", {}).get("data", [])
    latlng_stream = streams.get("latlng", {}).get("data", [])
    altitude_stream = streams.get("altitude", {}).get("data", [])
    heartrate_stream = streams.get("heartrate", {}).get("data", [])
    cadence_stream = streams.get("cadence", {}).get("data", [])

    stream_dict = {
        "time": time_stream,
        "latlng": latlng_stream,
        "altitude": altitude_stream,
        "distance": distance_stream,
        "heartrate": heartrate_stream,
        "cadence": cadence_stream
    }

    trackpoints = [
        build_trackpoint(idx, start_time, stream_dict)
        for idx in range(len(time_stream))
    ]

    tcx = f'''<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 http://www8.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd">
  <Activities>
    <Activity Sport="{sport}">
      <Id>{start_time.strftime("%Y-%m-%dT%H:%M:%SZ")}</Id>
      <Lap StartTime="{start_time.strftime("%Y-%m-%dT%H:%M:%SZ")}">
        <TotalTimeSeconds>{activity.get("elapsed_time", 0)}</TotalTimeSeconds>
        <DistanceMeters>{activity.get("distance", 0)}</DistanceMeters>
        <Calories>{activity.get("calories", 0)}</Calories>
        <Track>
{"".join(trackpoints)}        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>'''

    return tcx
