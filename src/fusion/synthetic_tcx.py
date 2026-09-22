"""
Synthetic TCX workout file generator.
Allows swim sessions to be registered in TrainingPeaks even when the watch was forgotten,
deriving the session from verified LAGO and StudentApp bookings.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..models import FusedWorkout, SwimReservation


def generate_synthetic_swim_tcx(
    workout: Optional[FusedWorkout] = None,
    reservation: Optional[SwimReservation] = None,
    distance_meters: float = 2000.0,
    duration_seconds: int = 3600,
    facility_name: str = "Pool",
) -> str:
    """
    Generate a valid TrainingPeaks-compatible TCX XML file for a swim session
    where the athlete forgot their watch.
    """
    start_time = datetime.now(timezone.utc)
    if workout:
        start_time = workout.start_time
        distance_meters = workout.distance_meters or distance_meters
        duration_seconds = workout.duration_seconds or duration_seconds
        facility_name = workout.title
    elif reservation:
        start_time = reservation.start_time
        duration_seconds = reservation.duration_seconds or duration_seconds
        facility_name = reservation.facility

    start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Generate evenly spaced trackpoints across duration (every 60 seconds)
    trackpoints = []
    step_seconds = 60
    num_points = max(2, duration_seconds // step_seconds)
    dist_step = distance_meters / num_points

    for i in range(num_points + 1):
        pt_time = start_time + timedelta(seconds=min(i * step_seconds, duration_seconds))
        pt_dist = round(min(i * dist_step, distance_meters), 1)
        pt_iso = pt_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        trackpoints.append(
            f'          <Trackpoint>\n'
            f'            <Time>{pt_iso}</Time>\n'
            f'            <DistanceMeters>{pt_dist}</DistanceMeters>\n'
            f'          </Trackpoint>'
        )

    trackpoints_xml = "\n".join(trackpoints)

    # Note: TrainingPeaks requires Sport="Other" for swim files imported via TCX
    tcx = f'''<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 http://www8.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd">
  <Activities>
    <Activity Sport="Other">
      <Id>{start_iso}</Id>
      <Lap StartTime="{start_iso}">
        <TotalTimeSeconds>{duration_seconds}</TotalTimeSeconds>
        <DistanceMeters>{distance_meters}</DistanceMeters>
        <Calories>450</Calories>
        <Intensity>Active</Intensity>
        <TriggerMethod>Manual</TriggerMethod>
        <Track>
{trackpoints_xml}
        </Track>
        <Notes>🏊 Verified Swim Session at {facility_name} (Watch forgotten - logged from pool reservation)</Notes>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>'''

    return tcx
