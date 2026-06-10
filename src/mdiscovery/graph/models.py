"""AS-10: Internal data model — Entity, Link, SemanticType, LinkDirection."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import json
import uuid


class SemanticType(str, Enum):
    PERSON = "Person"
    ORGANIZATION = "Organization"
    LOCATION = "Location"
    EVENT = "Event"
    DOCUMENT = "Document"
    VEHICLE = "Vehicle"
    PHONE = "Phone"
    EMAIL = "Email"
    ACCOUNT = "Account"
    UNKNOWN = "Unknown"


class LinkDirection(str, Enum):
    DIRECTED = "directed"
    UNDIRECTED = "undirected"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class Entity:
    label: str
    semantic_type: SemanticType = SemanticType.UNKNOWN
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    properties: dict[str, Any] = field(default_factory=dict)
    # Icon name from the assets/icons library ("" = derive from semantic type).
    icon: str = ""
    # Per-entity display attributes managed by the dossier UI:
    # "size" (node px), "font_size" (label px), "photo" (absolute image path).
    style: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "semantic_type": self.semantic_type.value,
            "properties": self.properties,
            "icon": self.icon,
            "style": self.style,
        }

    def properties_json(self) -> str:
        return json.dumps(self.properties)

    def style_json(self) -> str:
        return json.dumps(self.style)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        props = data.get("properties", {})
        if isinstance(props, str):
            props = json.loads(props)
        style = data.get("style", {})
        if isinstance(style, str):
            style = json.loads(style) if style else {}
        return cls(
            id=data["id"],
            label=data["label"],
            semantic_type=SemanticType(data.get("semantic_type", "Unknown")),
            properties=props,
            icon=data.get("icon", "") or "",
            style=style or {},
        )

    def to_cytoscape(self) -> dict:
        data = {
            "id": self.id,
            "label": self.label,
            "type": self.semantic_type.value,
            **{k: str(v) for k, v in self.properties.items()},
        }
        if self.icon:
            data["icon"] = self.icon
        photo = self.style.get("photo")
        if photo and Path(photo).is_absolute():
            data["photo"] = Path(photo).as_uri()
        if self.style.get("size"):
            data["_size"] = self.style["size"]
        if self.style.get("font_size"):
            data["_fontSize"] = self.style["font_size"]
        return {"data": data}


@dataclass
class Link:
    source_id: str
    target_id: str
    link_type: str = "relates_to"
    direction: LinkDirection = LinkDirection.DIRECTED
    strength: float = 1.0
    confidence: float = 1.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "link_type": self.link_type,
            "direction": self.direction.value,
            "strength": self.strength,
            "confidence": self.confidence,
            "properties": self.properties,
        }

    def properties_json(self) -> str:
        return json.dumps(self.properties)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Link":
        props = data.get("properties", {})
        if isinstance(props, str):
            props = json.loads(props)
        return cls(
            id=data["id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            link_type=data.get("link_type", "relates_to"),
            direction=LinkDirection(data.get("direction", "directed")),
            strength=float(data.get("strength", 1.0)),
            confidence=float(data.get("confidence", 1.0)),
            properties=props,
        )

    def to_cytoscape(self) -> dict:
        return {
            "data": {
                "id": self.id,
                "source": self.source_id,
                "target": self.target_id,
                "type": self.link_type,
                "direction": self.direction.value,
                "strength": self.strength,
                "confidence": self.confidence,
            }
        }
