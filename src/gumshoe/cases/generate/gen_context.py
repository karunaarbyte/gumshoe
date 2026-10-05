"""The frozen context every stage reads: pack, presets, the effective spec, seed and versions."""

from collections.abc import Mapping
from dataclasses import dataclass

from gumshoe.cases.core.canonical import canonical_json
from gumshoe.cases.core.hashing import domain_digest
from gumshoe.cases.generate.streams import Stream
from gumshoe.cases.model.entities import Spec
from gumshoe.cases.model.pack import Pack
from gumshoe.cases.model.spec import PRESETS, PresetDef, UnsupportedPreset
from gumshoe.cases.packs.check.capacity import hosted_specs

STAGES = ("roster", "truth", "timeline", "facts", "placement")  # 2d-2c appends gating
STAGE_VERSIONS: dict[str, int] = {
    "roster": 2,
    "truth": 1,
    "timeline": 1,
    "facts": 1,
    "placement": 1,
}
SKELETON_ALGO_VERSION = 2


def require_int(name: str, value: object) -> None:
    """A bool is an int in Python but never a seed or counter anyone meant."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int, not {type(value).__name__}")


@dataclass(frozen=True, eq=False)
class GenContext:
    pack: Pack
    presets: Mapping[str, PresetDef]
    spec: Spec
    seed: int
    preset: str
    spec_hash: str

    @classmethod
    def of(
        cls,
        pack: Pack,
        seed: int,
        preset: str,
        presets: Mapping[str, PresetDef] = PRESETS,
    ) -> "GenContext":
        """Refuses a preset the pack cannot host: the pack checks exclude presets that
        `derive_spec` alone would accept (too few hosting scenes, a matching that is too large)."""
        require_int("seed", seed)
        hosted = dict(hosted_specs(pack, presets))
        spec = hosted.get(preset)
        if spec is None:
            raise UnsupportedPreset(
                f"preset {preset!r} is not hosted by pack {pack.id!r} (hosted: {sorted(hosted)})"
            )
        spec_hash = domain_digest(
            "gumshoe.gen.spec.v1", canonical_json(spec.model_dump(mode="json"))
        )
        return cls(
            pack=pack, presets=presets, spec=spec, seed=seed, preset=preset, spec_hash=spec_hash
        )

    def stream(self, stage: str, counter: int = 0) -> Stream:
        """The stage's stream: keyed by seed, spec, stage version, counter and stage name."""
        require_int("counter", counter)
        if counter < 0:
            raise ValueError(f"counter must not be negative, not {counter}")
        return Stream.root(self.seed, self.spec_hash, STAGE_VERSIONS[stage], counter, stage)
