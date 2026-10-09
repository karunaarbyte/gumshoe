"""Pack text to a `Pack` plus every issue. Pure: it takes bytes, never touches a file.

The TOML layout: `[meta]` (its `META_FIELDS` are flattened into the pack), `[capacity]`, array
tables `slot_defs`, `families` and `victims`, and keyed tables (`location_defs.<key>`,
`record_defs`, `method_defs`, `motive_defs`, `roles`, `scene_types`) that become keyed lists.
Pydantic errors are rewritten as pack issues with key paths. Any stage 1 issue stops the load
(spec 5): no pack."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef
from gumshoe.cases.packs.catalogue import make
from gumshoe.cases.packs.issues import PackIssue, PackSeverity
from gumshoe.cases.packs.runner import check_pack, sorted_issues
from gumshoe.cases.packs.suggest import did_you_mean

KEYED = ("location_defs", "record_defs", "method_defs", "motive_defs", "roles", "scene_types")
LISTS = ("slot_defs", "families", "victims")
SECTIONS = frozenset({"meta", "capacity", *KEYED, *LISTS})
META_FIELDS = frozenset({"id", "skeleton_rev", "skin_rev", "slots", "presets", "smalltalk_allow"})


@dataclass(frozen=True)
class LoadResult:
    pack: Pack | None
    issues: tuple[PackIssue, ...]

    @property
    def ok(self) -> bool:
        return self.pack is not None and not any(
            i.severity is PackSeverity.ERROR for i in self.issues
        )


def reshape(raw: dict[str, Any]) -> dict[str, Any]:
    """The TOML tables as the dict `Pack` validates. Unknown sections and meta keys, a non-table
    meta and keyed sections that are not tables are dropped (`shape_issues` reports them); other
    values of the wrong shape are passed through so the schema stage names them."""
    out: dict[str, Any] = {}
    meta = raw.get("meta")
    if isinstance(meta, dict):
        out.update({k: v for k, v in meta.items() if k in META_FIELDS})
    for name, value in raw.items():
        if name == "meta" or name not in SECTIONS:
            continue
        if name in KEYED:
            if isinstance(value, dict):
                out[name] = [
                    {**item, "key": key} if isinstance(item, dict) else item
                    for key, item in value.items()
                ]
        else:
            out[name] = value
    defs = raw.get("record_defs")
    if isinstance(defs, dict):
        out["record_kinds"] = sorted(defs)
    return out


def shape_issues(raw: dict[str, Any]) -> list[PackIssue]:
    """Stage 1 issues `reshape` drops: unknown sections, unknown or misplaced meta keys, and a
    meta or keyed section that is not a table."""
    out = [
        make("UNKNOWN_KEY", name, did_you_mean(name, SECTIONS), key=name)
        for name in sorted(raw)
        if name not in SECTIONS
    ]
    meta = raw.get("meta")
    if isinstance(meta, dict):
        out += [
            make("UNKNOWN_KEY", f"meta.{key}", did_you_mean(key, META_FIELDS), key=key)
            for key in sorted(meta)
            if key not in META_FIELDS
        ]
    elif "meta" in raw:
        out.append(make("WRONG_TYPE", "meta", reason="meta must be a table"))
    for name in KEYED:
        if name in raw and not isinstance(raw[name], dict):
            out.append(make("WRONG_TYPE", name, reason=f"{name} must be a table of keyed tables"))
    return out


def _path(loc: tuple[int | str, ...], data: Any) -> str:
    """A key path from a pydantic location; list items are named by their key or id."""
    parts: list[str] = []
    node = data
    for part in loc:
        if isinstance(part, int):
            item = node[part] if isinstance(node, list) and 0 <= part < len(node) else None
            name = item.get("key", item.get("id")) if isinstance(item, dict) else None
            if isinstance(name, str):
                parts.append(name)
            elif parts:
                parts[-1] += f"[{part}]"
            else:
                parts.append(f"[{part}]")
            node = item
        else:
            parts.append(str(part))
            node = node.get(part) if isinstance(node, dict) else None
    if parts and loc and loc[0] in META_FIELDS:
        parts.insert(0, "meta")
    return ".".join(parts) or "pack"


def _schema_issues(exc: ValidationError, data: dict[str, Any]) -> list[PackIssue]:
    out: list[PackIssue] = []
    for error in exc.errors(include_url=False):
        loc = tuple(error["loc"])
        path = _path(loc, data)
        last = str(loc[-1]) if loc else "pack"
        if error["type"] == "missing":
            out.append(make("MISSING_FIELD", path, field=last))
        elif error["type"] == "extra_forbidden":
            out.append(make("UNKNOWN_KEY", path, key=last))
        else:
            out.append(make("WRONG_TYPE", path, reason=error["msg"]))
    return out


def load_pack(data: bytes, presets: Mapping[str, PresetDef] = PRESETS) -> LoadResult:
    """Parse, validate the schema, then run stages 2 to 7. Never raises on bad content."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return LoadResult(None, (make("TOML_SYNTAX", "file", reason=f"not UTF-8 ({exc.reason})"),))
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return LoadResult(None, (make("TOML_SYNTAX", "file", reason=str(exc)),))
    except RecursionError:
        return LoadResult(None, (make("TOML_SYNTAX", "file", reason="nested too deeply"),))
    issues = shape_issues(raw)
    shaped = reshape(raw)
    try:
        pack = Pack.model_validate(shaped)
    except ValidationError as exc:
        issues += _schema_issues(exc, shaped)
    else:
        if not issues:
            return LoadResult(pack, check_pack(pack, presets))
    return LoadResult(None, sorted_issues(issues))  # stage 1 errors stop everything (spec 5)
