"""Versioned layout resources, independent of campaign content packs."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.layout.intent import LayoutIntent

log = logging.getLogger(__name__)
RESOURCE_PATH = Path(__file__).parents[2] / 'content' / 'layout_templates'


class LayoutTemplate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    id: str
    version: str
    archetype: str
    template_ids: list[str]
    tags: list[str] = Field(default_factory=list)
    environment: Literal['indoor', 'outdoor', 'mixed']
    scale: Literal['small', 'medium', 'large'] = 'medium'
    part_bindings: dict[str, str]
    intent: LayoutIntent

    @model_validator(mode='after')
    def validate_resource(self):
        refs = {p.part_ref for p in self.intent.parts}
        if not self.id or not self.version or not self.template_ids:
            raise ValueError('missing catalog identity')
        if not set(self.part_bindings.values()) <= refs:
            raise ValueError('unknown binding target')
        if len(set(self.part_bindings.values())) != len(self.part_bindings):
            raise ValueError('ambiguous bindings')
        if any(p.anchors for p in self.intent.parts) or any(a.outside_id for a in self.intent.approaches):
            raise ValueError('campaign references in resource')
        environments = {p.environment for p in self.intent.parts}
        actual = 'mixed' if len(environments) > 1 else next(iter(environments))
        if self.environment != actual:
            raise ValueError('incorrect environment')
        return self

    @property
    def checksum(self) -> str:
        raw = json.dumps(self.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def load_catalog(path: Path | None = None) -> tuple[LayoutTemplate, ...]:
    result = {}
    for file in sorted((path or RESOURCE_PATH).glob('*.json')):
        try:
            entry = LayoutTemplate.model_validate_json(file.read_text(encoding='utf-8'))
            if entry.id in result:
                raise ValueError('duplicate template id')
            result[entry.id] = entry
        except (ValueError, OSError):
            log.warning('Rejected layout resource: %s', file.name)
    return tuple(result[key] for key in sorted(result))
