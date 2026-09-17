from copy import deepcopy

from features.wild import WildConfig
from features.sticky import StickyWild
from dataclasses import dataclass

@dataclass
class WildProcessingResult:

    grid: list[list[str]]

    original_wilds: int = 0

    expanded_cells: int = 0

    boom_cells: int = 0

class WildProcessor:

    def __init__(self, config: WildConfig):
        self.config = config
        self.sticky_wilds: list[StickyWild] = []

    def process_grid(
        self,
        grid: list[list[str]],
        regular_symbols: set[str],
        scatter_symbols: set[str] | None = None,
        bonus_symbols: set[str] | None = None
    ) -> WildProcessingResult:

        scatter_symbols = scatter_symbols or set()
        bonus_symbols = bonus_symbols or set()

        result = deepcopy(
            grid
        )

        processing_result = WildProcessingResult(
            grid=result
        )

        if not self.config.enabled:
            return processing_result

        # ==========================================
        # 1. Restore Sticky
        # ==========================================

        if self.config.sticky_enabled:

            self._restore_sticky_wilds(
                result
            )

        # ==========================================
        # 2. Original Wilds
        # ==========================================

        original_positions = (
            self._find_wilds(
                result
            )
        )

        processing_result.original_wilds = len(
            original_positions
        )

        # ==========================================
        # 3. Expanding
        # ==========================================

        if self.config.expanding_enabled:

            before_count = len(
                self._find_wilds(
                    result
                )
            )

            expanded_reels = set()

            for reel_index, row_index in (
                original_positions
            ):

                if reel_index in expanded_reels:
                    continue

                expanded_reels.add(
                    reel_index
                )

                self._expand_wild(
                    result,
                    reel_index
                )

            after_count = len(
                self._find_wilds(
                    result
                )
            )

            processing_result.expanded_cells = max(
                0,
                after_count - before_count
            )

        # ==========================================
        # 4. Boom
        # ==========================================

        if self.config.boom_enabled:

            wild_positions = (
                self._find_wilds(
                    result
                )
            )

            before_count = len(
                wild_positions
            )

            for reel_index, row_index in list(
                wild_positions
            ):

                self._apply_boom(
                    grid=result,
                    center_reel=reel_index,
                    center_row=row_index,
                    regular_symbols=regular_symbols,
                    scatter_symbols=scatter_symbols,
                    bonus_symbols=bonus_symbols
                )

            after_count = len(
                self._find_wilds(
                    result
                )
            )

            processing_result.boom_cells = max(
                0,
                after_count - before_count
            )

        # ==========================================
        # 5. Register Sticky
        # ==========================================

        if self.config.sticky_enabled:

            self._register_new_sticky_wilds(
                result
            )

        return processing_result

    # =================================================
    # FIND
    # =================================================

    def _find_wilds(
        self,
        grid
    ):

        result = []

        for reel_index, reel in enumerate(grid):

            for row_index, symbol in enumerate(reel):

                if symbol == self.config.symbol_id:

                    result.append(
                        (
                            reel_index,
                            row_index
                        )
                    )

        return result

    # =================================================
    # EXPANDING
    # =================================================

    def _expand_wild(
        self,
        grid,
        reel_index
    ):

        for row_index in range(
            len(grid[reel_index])
        ):

            grid[
                reel_index
            ][
                row_index
            ] = self.config.symbol_id

    # =================================================
    # BOOM
    # =================================================

    def _apply_boom(
        self,
        grid,
        center_reel,
        center_row,
        regular_symbols,
        scatter_symbols,
        bonus_symbols
    ):

        reel_count = len(grid)

        rows = len(
            grid[0]
        )

        radius = max(
            1,
            self.config.boom_radius
        )

        for reel_offset in range(
            -radius,
            radius + 1
        ):

            for row_offset in range(
                -radius,
                radius + 1
            ):

                if (
                    reel_offset == 0
                    and row_offset == 0
                ):
                    continue

                if (
                    not self.config.boom_diagonal
                    and reel_offset != 0
                    and row_offset != 0
                ):
                    continue

                target_reel = (
                    center_reel
                    + reel_offset
                )

                target_row = (
                    center_row
                    + row_offset
                )

                if not (
                    0 <= target_reel < reel_count
                ):
                    continue

                if not (
                    0 <= target_row < rows
                ):
                    continue

                symbol = (
                    grid[
                        target_reel
                    ][
                        target_row
                    ]
                )

                if (
                    symbol
                    in regular_symbols
                ):

                    grid[
                        target_reel
                    ][
                        target_row
                    ] = self.config.symbol_id

                    continue

                if (
                    symbol
                    in scatter_symbols
                    and self.config.boom_replace_scatter
                ):

                    grid[
                        target_reel
                    ][
                        target_row
                    ] = self.config.symbol_id

                    continue

                if (
                    symbol
                    in bonus_symbols
                    and self.config.boom_replace_bonus
                ):

                    grid[
                        target_reel
                    ][
                        target_row
                    ] = self.config.symbol_id

    # =================================================
    # STICKY
    # =================================================

    def _restore_sticky_wilds(
        self,
        grid
    ):

        active = []

        for sticky in self.sticky_wilds:

            if sticky.remaining_spins <= 0:
                continue

            if (
                sticky.reel < len(grid)
                and sticky.row < len(
                    grid[sticky.reel]
                )
            ):

                grid[
                    sticky.reel
                ][
                    sticky.row
                ] = self.config.symbol_id

                sticky.remaining_spins -= 1

                if sticky.remaining_spins > 0:

                    active.append(
                        sticky
                    )

        self.sticky_wilds = active

    def _register_new_sticky_wilds(
        self,
        grid
    ):

        existing_positions = {
            (
                sticky.reel,
                sticky.row
            )
            for sticky in self.sticky_wilds
        }

        for reel_index, row_index in self._find_wilds(
            grid
        ):

            position = (
                reel_index,
                row_index
            )

            if position in existing_positions:
                continue

            self.sticky_wilds.append(
                StickyWild(
                    reel=reel_index,
                    row=row_index,
                    remaining_spins=(
                        self.config.sticky_duration
                    )
                )
            )