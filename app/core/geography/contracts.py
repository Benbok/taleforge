"""Geography contracts: authored regions, locations and routes between concrete areas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GeographyError(Exception):
    """Invalid geography; ``code`` is stable for validation reports, ``refs`` names the culprits."""

    def __init__(self, code: str, *refs: str):
        super().__init__(f"{code}: {', '.join(refs)}" if refs else code)
        self.code = code
        self.refs = refs


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouteEndpoint(Model):
    node_ref: str
    area_ref: str | None = None


class NodeDraft(Model):
    ref: str
    kind: Literal["region", "location"]
    name: str
    plot_ref: str | None = None
    parent_ref: str | None = None
    entity_id: str | None = None  # filled when the node is materialized


class LinkDraft(Model):
    ref: str
    source: RouteEndpoint
    target: RouteEndpoint
    bidirectional: bool = True
    kind: str = "path"
    hidden: bool = False
    constraints: dict = Field(default_factory=dict)


class GeographyDraft(Model):
    nodes: tuple[NodeDraft, ...] = ()
    links: tuple[LinkDraft, ...] = ()
    start_ref: str | None = None


class GeographyView(Model):
    nodes: tuple[NodeDraft, ...] = ()
    links: tuple[LinkDraft, ...] = ()
    start_ref: str | None = None


class RoutePort(Model):
    node_ref: str
    area_ref: str
    area_id: str
    cells: tuple[tuple[int, int], ...] = ()
    ready: bool = False
