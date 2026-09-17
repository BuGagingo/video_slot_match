from dataclasses import dataclass

from engine.reel import Reel
from engine.evaluator import PaylineEvaluator
from engine.rng import create_rng, generate_time_seed, RNGAlgorithm
from features.wild import WildConfig
from features.scatter import ScatterConfig
from features.wild_processor import WildProcessor
from statistics.accumulator import StatisticsAccumulator, SimulationStatistics


@dataclass
class SimulationResult:
    spins: int
    total_bet: float
    total_win: float
    winning_spins: int
    max_win: float
    max_win_x: float
    statistics: SimulationStatistics

    @property
    def rtp(self) -> float:
        if self.total_bet <= 0:
            return 0.0
        return (self.total_win / self.total_bet) * 100.0

    @property
    def hit_rate(self) -> float:
        if self.spins <= 0:
            return 0.0
        return (self.winning_spins / self.spins) * 100.0

    @property
    def hit_frequency(self) -> float:
        if self.winning_spins <= 0:
            return 0.0
        return self.spins / self.winning_spins

    def merge(self, other: "SimulationResult"):
        self.spins += other.spins
        self.total_bet += other.total_bet
        self.total_win += other.total_win
        self.winning_spins += other.winning_spins
        if other.max_win > self.max_win:
            self.max_win = other.max_win
        if other.max_win_x > self.max_win_x:
            self.max_win_x = other.max_win_x
        self.statistics.merge(other.statistics)


def run_simulation_worker_task(args: dict) -> SimulationResult:
    simulator = SlotSimulator(
        reels=args["reels"],
        paylines=args["paylines"],
        paytable=args["paytable"],
        total_bet=args["total_bet"],
        payout_base=args["payout_base"],
        bet_per_line=args["bet_per_line"],
        rng_algorithm=args.get("rng_algorithm", RNGAlgorithm.PCG64),
        seed=args.get("seed"),
        wild_config=args["wild_config"],
        scatter_config=args["scatter_config"]
    )
    return simulator.run(spins=args["spins"], rows=args["rows"])


class SlotSimulator:

    def __init__(
        self,
        reels: list[Reel],
        paylines: list[str],
        paytable: dict,
        total_bet: float = 1.0,
        payout_base: str = "TOTAL_BET",
        bet_per_line: float | None = None,
        rng_algorithm: str = RNGAlgorithm.PCG64,
        seed: int | None = None,
        wild_config=None,
        scatter_config=None
    ):
        self.reels = reels
        self.paylines = paylines
        self.paytable = paytable
        self.payout_base = payout_base
        self.total_bet_per_spin = float(total_bet)

        if bet_per_line is None:
            self.bet_per_line = (self.total_bet_per_spin / len(paylines)) if len(paylines) > 0 else 0.0
        else:
            self.bet_per_line = float(bet_per_line)

        self.rng_algorithm = rng_algorithm
        self.seed = seed if seed is not None else generate_time_seed()
        self.rng = create_rng(algorithm=self.rng_algorithm, seed=self.seed)

        self.wild_config = wild_config if wild_config is not None else WildConfig(enabled=False)
        self.scatter_config = scatter_config if scatter_config is not None else ScatterConfig()

        self.wild_processor = WildProcessor(self.wild_config)

        scatter_symbols = {sc.symbol_id for sc in self.scatter_config.scatters if sc.enabled}

        self.evaluator = PaylineEvaluator(
            paytable=self.paytable,
            wild_symbol=self.wild_config.symbol_id if self.wild_config.enabled else None,
            scatter_symbols=scatter_symbols
        )
        self.statistics = StatisticsAccumulator(
            wild_symbol=self.wild_config.symbol_id if self.wild_config.enabled else None,
            scatter_symbols=scatter_symbols
        )

    def get_payout_base_value(self) -> float:
        if self.payout_base == "BET_PER_LINE":
            return self.bet_per_line
        return self.total_bet_per_spin

    def spin(self, rows: int):
        grid = []
        for reel in self.reels:
            stop_position = int(self.rng.integers(0, len(reel)))
            grid.append(reel.get_visible_symbols(stop_position, rows))
        return grid

    def run(self, spins: int, rows: int) -> SimulationResult:
        total_win = 0.0
        winning_spins = 0
        max_win = 0.0
        max_win_x = 0.0

        regular_symbols = set(self.paytable.keys())
        if self.wild_config.enabled:
            regular_symbols.discard(self.wild_config.symbol_id)

        scatter_symbols = {sc.symbol_id for sc in self.scatter_config.scatters if sc.enabled}
        regular_symbols.difference_update(scatter_symbols)

        payout_base_value = self.get_payout_base_value()

        for _ in range(spins):
            raw_grid = self.spin(rows=rows)
            self.statistics.add_grid(raw_grid)

            processed_grid = raw_grid
            if self.wild_config.enabled:
                processing = self.wild_processor.process_grid(
                    grid=raw_grid,
                    regular_symbols=regular_symbols,
                    scatter_symbols=scatter_symbols
                )
                processed_grid = processing.grid
                self.statistics.stats.wild.expanded_cells += processing.expanded_cells
                self.statistics.stats.wild.boom_cells += processing.boom_cells

            evaluation = self.evaluator.evaluate_spin(
                grid=processed_grid,
                paylines=self.paylines,
                payout_base_value=payout_base_value,
                payout_base_type=self.payout_base,
                scatter_config=self.scatter_config,
                total_bet=self.total_bet_per_spin
            )

            spin_win = evaluation.total_win
            total_win += spin_win

            self.statistics.add_evaluation(evaluation)
            self.statistics.add_spin_win(
                spin_win=spin_win,
                total_bet=self.total_bet_per_spin
            )

            if spin_win > 0:
                winning_spins += 1
            if spin_win > max_win:
                max_win = spin_win

            if self.total_bet_per_spin > 0:
                current_win_x = spin_win / self.total_bet_per_spin
                if current_win_x > max_win_x:
                    max_win_x = current_win_x

        total_bet = spins * self.total_bet_per_spin

        return SimulationResult(
            spins=spins,
            total_bet=total_bet,
            total_win=total_win,
            winning_spins=winning_spins,
            max_win=max_win,
            max_win_x=max_win_x,
            statistics=self.statistics.stats
        )