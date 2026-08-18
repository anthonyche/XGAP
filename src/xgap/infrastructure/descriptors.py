"""Backend descriptor objects and lightweight YAML loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


JsonMap = dict[str, Any]


class DescriptorError(ValueError):
    """Raised when a backend descriptor is malformed."""


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _split_inline_list(value: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    for char in value:
        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
        elif char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
        elif char == "," and not in_single and not in_double:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_inline_list(inner)]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _preprocess_yaml(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if "\t" in raw_line:
            raise DescriptorError("Tabs are not supported in XGAP YAML files")
        without_comment = _strip_comment(raw_line).rstrip()
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        lines.append((indent, without_comment.strip()))
    return lines


def _parse_yaml_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, content = lines[index]
    if current_indent < indent:
        return {}, index
    if current_indent > indent:
        raise DescriptorError(f"Unexpected indentation before: {content}")
    if content.startswith("- "):
        return _parse_yaml_list(lines, index, indent)
    return _parse_yaml_mapping(lines, index, indent)


def _parse_yaml_list(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[list[Any], int]:
    values: list[Any] = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise DescriptorError(f"Unexpected indentation before: {content}")
        if not content.startswith("- "):
            break
        item = content[2:].strip()
        index += 1
        if item:
            values.append(_parse_scalar(item))
        else:
            child, index = _parse_yaml_block(lines, index, indent + 2)
            values.append(child)
    return values, index


def _parse_yaml_mapping(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[JsonMap, int]:
    mapping: JsonMap = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise DescriptorError(f"Unexpected indentation before: {content}")
        if content.startswith("- "):
            break
        if ":" not in content:
            raise DescriptorError(f"Expected key/value line, got: {content}")
        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            raise DescriptorError("YAML mapping key must not be empty")
        index += 1
        if raw_value:
            mapping[key] = _parse_scalar(raw_value)
        else:
            if index >= len(lines) or lines[index][0] <= indent:
                mapping[key] = {}
            else:
                mapping[key], index = _parse_yaml_block(lines, index, lines[index][0])
    return mapping, index


def load_yaml_mapping(path: str | Path) -> JsonMap:
    """Load the repository's deterministic YAML subset.

    Always use the bundled parser so artifact meaning and hashes do not
    depend on whether an optional system YAML package is installed.
    """

    yaml_path = Path(path)
    text = yaml_path.read_text(encoding="utf-8")
    lines = _preprocess_yaml(text)
    parsed, index = _parse_yaml_block(lines, 0, 0)
    if index != len(lines):
        raise DescriptorError(f"Could not parse all of {yaml_path}")
    if not isinstance(parsed, dict):
        raise DescriptorError(f"{yaml_path} must contain a YAML mapping")
    return dict(parsed)


def _require_mapping(data: Mapping[str, Any], key: str) -> JsonMap:
    value = data.get(key)
    if not isinstance(value, dict):
        raise DescriptorError(f"Backend descriptor field '{key}' must be a mapping")
    return dict(value)


def _require_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise DescriptorError(f"Backend descriptor field '{key}' must be a non-empty string")
    return value


@dataclass(frozen=True)
class BackendDescriptor:
    """JSON-serializable backend descriptor.

    The descriptor records runtime and capability metadata only. It is
    intentionally separate from logical planning and compilation.
    """

    id: str
    engine: str
    language: str
    data_model: str
    deployment: JsonMap = field(default_factory=dict)
    capabilities: JsonMap = field(default_factory=dict)
    runtime: JsonMap = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackendDescriptor":
        return cls(
            id=_require_string(data, "id"),
            engine=_require_string(data, "engine"),
            language=_require_string(data, "language"),
            data_model=_require_string(data, "data_model"),
            deployment=_require_mapping(data, "deployment"),
            capabilities=_require_mapping(data, "capabilities"),
            runtime=_require_mapping(data, "runtime"),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BackendDescriptor":
        return cls.from_dict(load_yaml_mapping(path))

    def to_dict(self) -> JsonMap:
        return {
            "id": self.id,
            "engine": self.engine,
            "language": self.language,
            "data_model": self.data_model,
            "deployment": dict(self.deployment),
            "capabilities": dict(self.capabilities),
            "runtime": dict(self.runtime),
        }
