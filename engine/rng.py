import time
import secrets
import numpy as np
from numpy.random import Generator, PCG64, MT19937, Philox, SFC64


class RNGAlgorithm:
    PCG64 = "PCG64"
    MT19937 = "MT19937"
    PHILOX = "Philox"
    SFC64 = "SFC64"


def generate_time_seed() -> int:
    """Генерация уникального 64-битного сида на основе наносекунд времени и энтропии ОС."""
    return (time.time_ns() ^ secrets.randbits(32)) % (2**63 - 1)


def create_rng(
    algorithm: str = RNGAlgorithm.PCG64,
    seed: int | None = None
) -> Generator:
    """
    Создает экземпляр numpy.random.Generator.
    Если seed не указан (None), используется генерация от времени.
    """
    if seed is None:
        seed = generate_time_seed()

    if algorithm == RNGAlgorithm.MT19937:
        bit_generator = MT19937(seed)
    elif algorithm == RNGAlgorithm.PHILOX:
        bit_generator = Philox(seed)
    elif algorithm == RNGAlgorithm.SFC64:
        bit_generator = SFC64(seed)
    else:  # PCG64 по умолчанию
        bit_generator = PCG64(seed)

    return Generator(bit_generator)