from dataclasses import dataclass, field


@dataclass
class SingleScatterConfig:
    enabled: bool = False
    symbol_id: str = "SCATTER"
    # Разрешенные барабаны (0..4)
    allowed_reels: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    # Таблица выплат (множитель от Total Bet за количество символов на экране)
    # {2: 1.0, 3: 5.0, 4: 20.0, 5: 100.0}
    pays: dict[int, float] = field(default_factory=dict)


@dataclass
class ScatterConfig:
    scatters: list[SingleScatterConfig] = field(default_factory=list)