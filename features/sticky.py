from dataclasses import dataclass


@dataclass
class StickyWild:
    reel: int
    row: int
    remaining_spins: int