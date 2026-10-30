"""What differs between kinds of generated artwork; everything else lives in the lifecycle service."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtworkRecipe:
    kind: str  # stored in artworks.kind
    media_subdir: str  # under MEDIA_DIR
    purpose: str  # LlmCall.purpose of the generation attempt
    noun: str  # accusative, for messages: "подложку"
    source: Callable[..., Any]  # (viewer, subject[, session]) -> public source (dict or awaitable); its digest decides staleness
    permitted: Callable[[Any], bool]  # may this viewer start generation
    blocker: Callable[[dict], str | None]  # reason the source is not ready, or None
    init_image: Callable[[dict], bytes | None]  # img2img input derived from the source
    prompt_source: Callable[[dict], dict]  # {"identity","appearance","personality"} sent to translator/generator
    url: Callable[[str, str, str], str]  # (campaign_id, subject_id, image_id) -> file URL
    control_image: Callable[[dict], bytes | None] | None = None  # optional ControlNet input derived from the source
    source_needs_session: bool = False  # source(viewer, subject, session) is async and reads the database
    denied: str = "Создавать картинку может только администратор"
