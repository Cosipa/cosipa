"""Validation and low-level edits shared by generated SVG assets."""

import re
import xml.etree.ElementTree as ET

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
SVG_NS = "{" + SVG_NAMESPACE + "}"
ASSET_DIGEST_LENGTH = 12
ASSET_NAME = re.compile(r"[a-z0-9-]+")
GENERATED_ASSET_NAME = re.compile(
    rf"[a-z0-9-]+\.[a-f0-9]{{{ASSET_DIGEST_LENGTH}}}\.svg"
)
HEX_DIGITS = re.compile(r"[A-Fa-f0-9]+")
PGP_MIN_FINGERPRINT_LENGTH = 40
PGP_MAX_FINGERPRINT_LENGTH = 64
PGP_KEY_ID_LENGTH = 16
FORBIDDEN_ELEMENTS = {"script", "foreignObject"}


def validate_asset_name(name: str) -> None:
    if not ASSET_NAME.fullmatch(name):
        raise ValueError("Invalid generated asset name")


def is_generated_asset(name: str) -> bool:
    return GENERATED_ASSET_NAME.fullmatch(name) is not None


def pgp_key_id(fingerprint: str) -> str:
    valid_length = (
        PGP_MIN_FINGERPRINT_LENGTH <= len(fingerprint) <= PGP_MAX_FINGERPRINT_LENGTH
    )
    if not valid_length or not HEX_DIGITS.fullmatch(fingerprint):
        raise ValueError("Invalid configured public PGP fingerprint")
    return "0x" + fingerprint[-PGP_KEY_ID_LENGTH:].upper()


def validate_attribute(name: str, value: str) -> None:
    is_event_handler = name.lower().startswith("on")
    is_external_reference = name.split("}")[-1] == "href" and not value.startswith("#")
    if is_event_handler or is_external_reference:
        raise ValueError("External/active SVG references are forbidden")


def validate_svg(payload: bytes) -> None:
    root = ET.fromstring(payload)
    if root.tag != SVG_NS + "svg":
        raise ValueError("Generated asset is not an SVG")
    for node in root.iter():
        if node.tag.split("}")[-1] in FORBIDDEN_ELEMENTS:
            raise ValueError("Active SVG content is forbidden")
        for name, value in node.attrib.items():
            validate_attribute(name, value)


def required_element(root: ET.Element, path: str, message: str) -> ET.Element:
    element = root.find(path)
    if element is None:
        raise ValueError(message)
    return element


def replace_palette(stylesheet: str, palette: dict[str, str]) -> str:
    """Replace only the first declaration of each snk palette variable."""
    for name, color in palette.items():
        declaration = re.compile(r"--" + re.escape(name) + r":[^;}]+")
        stylesheet, count = declaration.subn(f"--{name}:#{color}", stylesheet, count=1)
        if count != 1:
            raise ValueError(f"Snake SVG is missing palette entry {name}")
    return stylesheet
