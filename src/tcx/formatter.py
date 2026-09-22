"""
TCX file validation, formatting, and manipulation utilities.
"""
import logging
import re
from pathlib import Path
from typing import Tuple, Optional
from defusedxml.minidom import parseString
from tcxreader.tcxreader import TCXReader

from ..models import Sport


logger = logging.getLogger(__name__)


def read_xml_file(file_path: str) -> str:
    """Read XML file content as string."""
    try:
        with open(file_path, "r", encoding="utf-8") as xml_file:
            return xml_file.read()
    except Exception as err:
        logger.error("Failed to read XML file %s: %s", file_path, str(err))
        raise


def write_xml_file(file_path: str, content: str) -> None:
    """Write string content to XML file."""
    try:
        with open(file_path, "w", encoding="utf-8") as xml_file:
            xml_file.write(content)
    except Exception as err:
        logger.error("Failed to write XML file %s: %s", file_path, str(err))
        raise


def extend_tcx_duration(xml_content: str, target_duration_seconds: int) -> str:
    """
    Ensure the TCX file duration reflects the full workout slot (e.g. 1h45m),
    preventing TrainingPeaks from displaying cut-off time when watch rest periods were paused.
    """
    time_matches = list(re.finditer(r"<TotalTimeSeconds>(\d+(?:\.\d+)?)</TotalTimeSeconds>", xml_content))
    if not time_matches:
        return xml_content

    current_total = sum(float(m.group(1)) for m in time_matches)
    if current_total >= target_duration_seconds:
        return xml_content

    diff = target_duration_seconds - current_total
    last_match = time_matches[-1]
    new_lap_time = round(float(last_match.group(1)) + diff, 1)

    # Replace last TotalTimeSeconds
    start, end = last_match.span()
    xml_content = xml_content[:start] + f"<TotalTimeSeconds>{new_lap_time}</TotalTimeSeconds>" + xml_content[end:]

    # Find Activity Id or StartTime to calculate end timestamp
    id_match = re.search(r"<Activity[^>]*>\s*<Id>([^<]+)</Id>", xml_content)
    if id_match:
        try:
            from datetime import datetime, timedelta
            start_dt = datetime.fromisoformat(id_match.group(1).replace("Z", "+00:00"))
            end_dt = start_dt + timedelta(seconds=target_duration_seconds)
            end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Find the last DistanceMeters in the file
            dist_matches = list(re.finditer(r"<DistanceMeters>(\d+(?:\.\d+)?)</DistanceMeters>", xml_content))
            last_dist = dist_matches[-1].group(1) if dist_matches else "0.0"

            # Insert resting/cooldown trackpoint before the last </Track>
            last_track_idx = xml_content.rfind("</Track>")
            if last_track_idx != -1:
                padding_tp = (
                    f"\n          <Trackpoint>\n"
                    f"            <Time>{end_iso}</Time>\n"
                    f"            <DistanceMeters>{last_dist}</DistanceMeters>\n"
                    f"          </Trackpoint>\n        "
                )
                xml_content = xml_content[:last_track_idx] + padding_tp + xml_content[last_track_idx:]
        except Exception as err:
            logger.debug("Failed to append final slot trackpoint to TCX: %s", err)

    return xml_content


def format_swim_tcx(file_path: str, target_duration_seconds: Optional[int] = None) -> None:
    """Format TCX file for swimming activities to ensure TrainingPeaks compatibility."""
    xml_content = read_xml_file(file_path)

    xml_content = xml_content.replace(
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">',
        '<TrainingCenterDatabase xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" xsi:schemaLocation="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 http://www8.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd">'
    )

    xml_content = re.sub(r"<Value>(\d+)\.0</Value>", r"<Value>\1</Value>", xml_content)
    xml_content = re.sub(r'<Activity Sport="Swim">', r'<Activity Sport="Other">', xml_content)

    if target_duration_seconds and target_duration_seconds > 0:
        xml_content = extend_tcx_duration(xml_content, target_duration_seconds)

    write_xml_file(file_path, xml_content)


def format_xml_file(file_path: str) -> None:
    """Format XML file with clean indentation."""
    try:
        xml_content = read_xml_file(file_path)
        xml_dom = parseString(xml_content)
        formatted_xml = xml_dom.toprettyxml(indent="  ")
        write_xml_file(file_path, formatted_xml)
    except Exception as err:
        logger.warning(
            "Failed to format XML file %s: %s. File saved without formatting.",
            file_path,
            str(err)
        )


def validate_tcx_file(file_path: str) -> Tuple[bool, Optional[TCXReader]]:
    """Validate TCX file structure and return parsed data if valid."""
    xml_content = read_xml_file(file_path)
    if not xml_content.strip():
        logger.error("The TCX file is empty: %s", file_path)
        return False, None

    tcx_reader = TCXReader()
    try:
        data = tcx_reader.read(file_path, only_gps=False)
        logger.info(
            "TCX file is valid: %s. Distance covered: %d meters",
            file_path,
            data.distance
        )
        return True, data
    except Exception as err:
        logger.error("Invalid TCX file %s: %s", file_path, str(err))
        return False, None
