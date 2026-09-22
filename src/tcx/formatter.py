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


def format_swim_tcx(file_path: str) -> None:
    """Format TCX file for swimming activities to ensure TrainingPeaks compatibility."""
    xml_content = read_xml_file(file_path)

    xml_content = xml_content.replace(
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">',
        '<TrainingCenterDatabase xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" xsi:schemaLocation="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 http://www8.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd">'
    )

    xml_content = re.sub(r"<Value>(\d+)\.0</Value>", r"<Value>\1</Value>", xml_content)
    xml_content = re.sub(r'<Activity Sport="Swim">', r'<Activity Sport="Other">', xml_content)

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
        data = tcx_reader.read(file_path)
        logger.info(
            "TCX file is valid: %s. Distance covered: %d meters",
            file_path,
            data.distance
        )
        return True, data
    except Exception as err:
        logger.error("Invalid TCX file %s: %s", file_path, str(err))
        return False, None
