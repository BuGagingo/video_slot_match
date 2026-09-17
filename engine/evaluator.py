from dataclasses import dataclass, field
from typing import Dict, List
from features.scatter import ScatterConfig


@dataclass
class LineWin:
    line_index: int
    line_pattern: str
    symbol: str
    match_count: int
    multiplier: float
    payout_base_value: float
    payout_base_type: str
    win: float
    wild_count: int = 0


@dataclass
class ScatterWin:
    symbol: str
    count: int
    multiplier: float
    win: float


@dataclass
class SpinEvaluation:
    total_win: float
    line_wins: list[LineWin] = field(default_factory=list)
    scatter_wins: list[ScatterWin] = field(default_factory=list)


class PaylineEvaluator:

    def __init__(
        self,
        paytable: Dict[str, Dict[int, float]],
        wild_symbol: str | None = None,
        scatter_symbols: set[str] | None = None
    ):
        self.paytable = paytable
        self.wild_symbol = wild_symbol
        self.scatter_symbols = scatter_symbols or set()

    def get_line_symbols(self, grid: List[List[str]], line: str) -> list[str]:
        result = []
        for reel_index, row_char in enumerate(line):
            row_index = int(row_char)
            result.append(grid[reel_index][row_index])
        return result

    def get_candidate_symbols(self, symbols: list[str]) -> set[str]:
        candidates = set()
        for symbol in symbols:
            # Скаттеры и Wild не считаются обычными символами на линиях
            if symbol in self.scatter_symbols:
                continue
            if self.wild_symbol is not None and symbol == self.wild_symbol:
                continue
            if symbol in self.paytable:
                candidates.add(symbol)
        return candidates

    def evaluate_candidate(self, symbols: list[str], target_symbol: str) -> tuple[int, int]:
        match_count = 0
        wild_count = 0

        for symbol in symbols:
            if symbol == target_symbol:
                match_count += 1
                continue
            if self.wild_symbol is not None and symbol == self.wild_symbol:
                match_count += 1
                wild_count += 1
                continue
            break

        return match_count, wild_count

    def evaluate_line(
        self,
        grid: List[List[str]],
        line: str,
        payout_base_value: float,
        payout_base_type: str,
        line_index: int = 0
    ) -> LineWin | None:
        symbols = self.get_line_symbols(grid=grid, line=line)
        if not symbols:
            return None

        candidates = self.get_candidate_symbols(symbols)

        # Линия целиком из Wild
        if (
            not candidates
            and self.wild_symbol in self.paytable
            and all(symbol == self.wild_symbol for symbol in symbols)
        ):
            candidates.add(self.wild_symbol)

        best_win = None

        for target_symbol in candidates:
            match_count, wild_count = self.evaluate_candidate(symbols, target_symbol)
            multiplier = self.paytable.get(target_symbol, {}).get(match_count, 0.0)

            if multiplier <= 0:
                continue

            win = float(payout_base_value) * float(multiplier)
            result = LineWin(
                line_index=line_index,
                line_pattern=line,
                symbol=target_symbol,
                match_count=match_count,
                multiplier=multiplier,
                payout_base_value=payout_base_value,
                payout_base_type=payout_base_type,
                win=win,
                wild_count=wild_count
            )

            if best_win is None or result.win > best_win.win:
                best_win = result

        return best_win

    def evaluate_scatters(
        self,
        grid: List[List[str]],
        scatter_config: ScatterConfig | None,
        total_bet: float
    ) -> list[ScatterWin]:
        if not scatter_config:
            return []

        scatter_wins = []
        for sc in scatter_config.scatters:
            if not sc.enabled:
                continue

            # Подсчет общего числа выпадений скаттера по всему видимому экрану
            count = sum(col.count(sc.symbol_id) for col in grid)
            multiplier = sc.pays.get(count, 0.0)

            if multiplier > 0:
                win = total_bet * multiplier
                scatter_wins.append(
                    ScatterWin(
                        symbol=sc.symbol_id,
                        count=count,
                        multiplier=multiplier,
                        win=win
                    )
                )

        return scatter_wins

    def evaluate_spin(
        self,
        grid: List[List[str]],
        paylines: List[str],
        payout_base_value: float,
        payout_base_type: str,
        scatter_config: ScatterConfig | None = None,
        total_bet: float = 1.0
    ) -> SpinEvaluation:
        total_win = 0.0
        line_wins = []

        # 1. Линии выплат
        for line_index, line in enumerate(paylines):
            result = self.evaluate_line(
                grid=grid,
                line=line,
                payout_base_value=payout_base_value,
                payout_base_type=payout_base_type,
                line_index=line_index
            )
            if result is not None:
                total_win += result.win
                line_wins.append(result)

        # 2. Скаттеры
        scatter_wins = self.evaluate_scatters(grid, scatter_config, total_bet)
        for sw in scatter_wins:
            total_win += sw.win

        return SpinEvaluation(
            total_win=total_win,
            line_wins=line_wins,
            scatter_wins=scatter_wins
        )