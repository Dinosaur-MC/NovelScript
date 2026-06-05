"""JSON Patch operation model (RFC 6902).

Used throughout the pipeline to represent AI-generated patches,
manual edits, and structured diffs.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class JsonPatchOp(BaseModel):
    """A single JSON Patch operation as defined by RFC 6902.

    ``op``  — one of *add*, *remove*, *replace*, *move*, *copy*, *test*.
    ``path`` — JSON Pointer to the target location.
    ``value`` — the value to apply (required for *add*, *replace*, *test*).
    ``from_`` — JSON Pointer source location (required for *move*, *copy*).
    """

    op: Literal["add", "remove", "replace", "move", "copy", "test"] = Field(
        ..., description="Patch operation type"
    )
    path: str = Field(..., description="JSON Pointer path, e.g. /characters/0/name")
    value: Optional[Any] = Field(
        None, description="Value for add / replace / test operations"
    )
    from_: Optional[str] = Field(
        None,
        alias="from",
        description="Source JSON Pointer for move / copy operations",
    )

    model_config = {"populate_by_name": True}
