from dataclasses import dataclass, field


@dataclass
class WildConfig:
    enabled: bool = True

    symbol_id: str = "WILD"

    # На каких барабанах может выпадать Wild.
    # Индексация внутри движка: 0..4
    allowed_reels: list[int] = field(
        default_factory=lambda: [1, 2, 3]
    )

    substitutes_regular: bool = True
    substitutes_scatter: bool = False
    substitutes_bonus: bool = False

    # Expanding
    expanding_enabled: bool = False
    expanding_full_reel: bool = True

    # Sticky
    sticky_enabled: bool = False
    sticky_duration: int = 3

    # Boom
    boom_enabled: bool = False
    boom_radius: int = 1
    boom_diagonal: bool = True

    boom_replace_scatter: bool = False
    boom_replace_bonus: bool = False