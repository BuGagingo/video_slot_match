from dataclasses import dataclass


@dataclass
class ValidationMessage:
    severity: str
    category: str
    message: str


class ModelValidator:

    def validate(
        self,
        reels,
        paytable,
        paylines,
        rows,
        wild_config=None,
        scatter_config=None
    ):
        messages = []

        if len(reels) != 5:
            messages.append(
                ValidationMessage(
                    severity="ERROR",
                    category="REELS",
                    message="Game must contain exactly 5 reels."
                )
            )

        known_symbols = set(paytable.keys())
        if wild_config and wild_config.enabled:
            known_symbols.add(wild_config.symbol_id)

        scatter_map = {}
        if scatter_config:
            for sc in scatter_config.scatters:
                if sc.enabled:
                    known_symbols.add(sc.symbol_id)
                    scatter_map[sc.symbol_id] = sc

        for reel_index, reel in enumerate(reels):
            if len(reel) < rows:
                messages.append(
                    ValidationMessage(
                        severity="ERROR",
                        category="REELS",
                        message=(
                            f"Reel {reel_index + 1} contains only {len(reel)} symbols. "
                            f"At least {rows} are required."
                        )
                    )
                )

            for symbol in reel.symbols:
                if symbol not in known_symbols:
                    messages.append(
                        ValidationMessage(
                            severity="ERROR",
                            category="SYMBOLS",
                            message=f"Unknown symbol '{symbol}' on Reel {reel_index + 1}."
                        )
                    )

        # Валидация барабанов для Wild
        if wild_config and wild_config.enabled:
            wild_id = wild_config.symbol_id
            for reel_index, reel in enumerate(reels):
                if wild_id in reel.symbols and reel_index not in wild_config.allowed_reels:
                    messages.append(
                        ValidationMessage(
                            severity="ERROR",
                            category="WILD",
                            message=(
                                f"Wild '{wild_id}' exists on Reel {reel_index + 1}, "
                                f"but this reel is disabled in Wild settings."
                            )
                        )
                    )

        # Валидация барабанов для Scatters
        for sc_id, sc in scatter_map.items():
            for reel_index, reel in enumerate(reels):
                if sc_id in reel.symbols and reel_index not in sc.allowed_reels:
                    messages.append(
                        ValidationMessage(
                            severity="ERROR",
                            category="SCATTER",
                            message=(
                                f"Scatter '{sc_id}' exists on Reel {reel_index + 1}, "
                                f"but this reel is disabled in Scatter settings."
                            )
                        )
                    )

        return messages