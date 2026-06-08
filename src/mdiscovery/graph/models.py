"""AS-10: Internal data model — Entity, Link, SemanticType, LinkDirection."""

from dataclasses import dataclass, field
from enum import Enum
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "semantic_type": self.semantic_type.value,
            "properties": self.properties,
        }

    def properties_json(self) -> str:
        return json.dumps(self.properties)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        props = data.get("properties", {})
        if isinstance(props, str):
            props = json.loads(props)
        return cls(
            id=data["id"],
            label=data["label"],
            semantic_type=SemanticType(data.get("semantic_type", "Unknown")),
            properties=props,
        )

    def to_cytoscape(self) -> dict:
        return {
            "data": {
                "id": self.id,
                "label": self.label,
                "type": self.semantic_type.value,
                **{k: str(v) for k, v in self.properties.items()},
            }
        }


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
