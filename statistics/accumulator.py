from collections import defaultdict
from dataclasses import dataclass, field


def _int_dict():
    return defaultdict(int)


def _combination_dict():
    return defaultdict(CombinationStat)


def _symbol_dict():
    return defaultdict(SymbolStat)


def _reel_symbol_dict():
    return defaultdict(_int_dict)


def _scatter_stat_dict():
    return defaultdict(ScatterStat)


@dataclass
class CombinationStat:
    hits: int = 0
    total_win: float = 0.0


@dataclass
class SymbolStat:
    hits: int = 0
    total_win: float = 0.0


@dataclass
class ScatterStat:
    hits_by_count: dict = field(default_factory=_int_dict)
    total_win: float = 0.0
    spins_with_scatter: int = 0

    def merge(self, other: "ScatterStat"):
        for k, v in other.hits_by_count.items():
            self.hits_by_count[k] += v
        self.total_win += other.total_win
        self.spins_with_scatter += other.spins_with_scatter


@dataclass
class WildStat:
    landed: int = 0
    spins_with_wild: int = 0
    wins_with_wild: int = 0
    win_amount_with_wild: float = 0.0
    expanded_cells: int = 0
    boom_cells: int = 0

    def merge(self, other: "WildStat"):
        self.landed += other.landed
        self.spins_with_wild += other.spins_with_wild
        self.wins_with_wild += other.wins_with_wild
        self.win_amount_with_wild += other.win_amount_with_wild
        self.expanded_cells += other.expanded_cells
        self.boom_cells += other.boom_cells


@dataclass
class SimulationStatistics:

    combinations: dict = field(default_factory=_combination_dict)
    symbols: dict = field(default_factory=_symbol_dict)
    symbol_generated: dict = field(default_factory=_int_dict)
    reel_symbol_generated: dict = field(default_factory=_reel_symbol_dict)
    win_distribution: dict = field(default_factory=_int_dict)
    wild: WildStat = field(default_factory=WildStat)
    scatters: dict = field(default_factory=_scatter_stat_dict)

    def merge(self, other: "SimulationStatistics"):
        for k, v in other.combinations.items():
            self.combinations[k].hits += v.hits
            self.combinations[k].total_win += v.total_win

        for k, v in other.symbols.items():
            self.symbols[k].hits += v.hits
            self.symbols[k].total_win += v.total_win

        for k, v in other.symbol_generated.items():
            self.symbol_generated[k] += v

        for r_idx, r_dict in other.reel_symbol_generated.items():
            for sym, cnt in r_dict.items():
                self.reel_symbol_generated[r_idx][sym] += cnt

        for k, v in other.win_distribution.items():
            self.win_distribution[k] += v

        self.wild.merge(other.wild)

        for sym, sc_stat in other.scatters.items():
            self.scatters[sym].merge(sc_stat)


class StatisticsAccumulator:

    def __init__(self, wild_symbol: str | None = None, scatter_symbols: set[str] | None = None):
        self.wild_symbol = wild_symbol
        self.scatter_symbols = scatter_symbols or set()
        self.stats = SimulationStatistics()

    def add_grid(self, grid: list[list[str]]):
        wild_found = False
        scatters_found = set()

        for reel_index, reel in enumerate(grid):
            for symbol in reel:
                self.stats.symbol_generated[symbol] += 1
                self.stats.reel_symbol_generated[reel_index][symbol] += 1

                if self.wild_symbol and symbol == self.wild_symbol:
                    self.stats.wild.landed += 1
                    wild_found = True

                if symbol in self.scatter_symbols:
                    scatters_found.add(symbol)

        if wild_found:
            self.stats.wild.spins_with_wild += 1

        for sc_sym in scatters_found:
            self.stats.scatters[sc_sym].spins_with_scatter += 1

    def add_evaluation(self, evaluation):
        for win in evaluation.line_wins:
            combination_key = (win.symbol, win.match_count)
            combination_stat = self.stats.combinations[combination_key]
            combination_stat.hits += 1
            combination_stat.total_win += win.win

            symbol_stat = self.stats.symbols[win.symbol]
            symbol_stat.hits += 1
            symbol_stat.total_win += win.win

            if win.wild_count > 0:
                self.stats.wild.wins_with_wild += 1
                self.stats.wild.win_amount_with_wild += win.win

        for sc_win in evaluation.scatter_wins:
            sc_stat = self.stats.scatters[sc_win.symbol]
            sc_stat.hits_by_count[sc_win.count] += 1
            sc_stat.total_win += sc_win.win

            # Учитываем также в общей символьной статистике
            symbol_stat = self.stats.symbols[sc_win.symbol]
            symbol_stat.hits += 1
            symbol_stat.total_win += sc_win.win

    def add_spin_win(self, spin_win: float, total_bet: float):
        if total_bet <= 0:
            return
        win_x = spin_win / total_bet
        bucket = self.get_win_bucket(win_x)
        self.stats.win_distribution[bucket] += 1

    @staticmethod
    def get_win_bucket(win_x: float) -> str:
        if win_x == 0:
            return "0x"
        if win_x < 1:
            return "0-1x"
        if win_x < 2:
            return "1-2x"
        if win_x < 5:
            return "2-5x"
        if win_x < 10:
            return "5-10x"
        if win_x < 20:
            return "10-20x"
        if win_x < 50:
            return "20-50x"
        if win_x < 100:
            return "50-100x"
        if win_x < 500:
            return "100-500x"
        if win_x < 1000:
            return "500-1000x"
        return "1000x+"