from dataclasses import dataclass


@dataclass
class Reel:
    symbols: list[str]

    def __len__(self):
        return len(self.symbols)

    def get_visible_symbols(
        self,
        stop_position: int,
        rows: int
    ) -> list[str]:

        result = []

        reel_length = len(self.symbols)

        for offset in range(rows):
            index = (stop_position + offset) % reel_length
            result.append(self.symbols[index])

        return result