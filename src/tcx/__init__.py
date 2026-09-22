"""
TCX parsing, conversion, and formatting tools.
"""
from .builder import build_trackpoint, generate_tcx_from_streams
from .formatter import (
    read_xml_file,
    write_xml_file,
    format_swim_tcx,
    format_xml_file,
    validate_tcx_file,
)
from .processor import TrackpointProcessor

__all__ = [
    "build_trackpoint",
    "generate_tcx_from_streams",
    "read_xml_file",
    "write_xml_file",
    "format_swim_tcx",
    "format_xml_file",
    "validate_tcx_file",
    "TrackpointProcessor",
]
