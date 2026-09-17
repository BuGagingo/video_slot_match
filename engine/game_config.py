from dataclasses import dataclass, field


@dataclass
class SymbolConfig:
    symbol_id: str
    name: str

    pay_2: float = 0.0
    pay_3: float = 0.0
    pay_4: float = 0.0
    pay_5: float = 0.0


@dataclass
class GameConfig:
    game_name: str = "New Slot"

    reels: int = 5
    rows: int = 3

    active_lines: int = 20

    # Основная ставка
    total_bet: float = 1.0

    # Альтернативный режим
    bet_per_line: float = 0.05

    # TOTAL_BET включён по умолчанию
    payout_base: str = "TOTAL_BET"

    simulation_spins: int = 100_000

    symbols: list[SymbolConfig] = field(
        default_factory=list
    )

    reel_strips: list[list[str]] = field(
        default_factory=lambda: [
            [],
            [],
            [],
            [],
            []
        ]
    )