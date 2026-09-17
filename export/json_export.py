import json
from engine.simulator import SimulationResult


def export_simulation_to_json(filepath: str, result: SimulationResult, config_dict: dict, reels: list):
    combs_list = []
    for (sym, cnt), cstat in sorted(result.statistics.combinations.items()):
        combs_list.append({
            "symbol": sym,
            "count": cnt,
            "hits": cstat.hits,
            "total_win": cstat.total_win
        })

    scatters_dict = {}
    for sc_sym, sc_stat in result.statistics.scatters.items():
        scatters_dict[sc_sym] = {
            "spins_with_scatter": sc_stat.spins_with_scatter,
            "total_win": sc_stat.total_win,
            "hits_by_count": {str(k): v for k, v in sc_stat.hits_by_count.items()}
        }

    symbols_dict = {}
    for sym, s_stat in result.statistics.symbols.items():
        symbols_dict[sym] = {
            "hits": s_stat.hits,
            "total_win": s_stat.total_win,
            "generated": result.statistics.symbol_generated.get(sym, 0)
        }

    # Анализ барабанов и весов
    reel_weights = {}
    all_symbols = sorted(result.statistics.symbol_generated.keys())
    for sym in all_symbols:
        reel_weights[sym] = {}
        for i in range(5):
            r_symbols = reels[i].symbols if i < len(reels) else []
            cnt = r_symbols.count(sym)
            pct = (cnt / len(r_symbols) * 100.0) if len(r_symbols) > 0 else 0.0
            reel_weights[sym][f"Reel_{i+1}"] = {
                "count": cnt,
                "percent": pct
            }

    data = {
        "configuration": config_dict,
        "reel_strips_analysis": {
            "lengths": [len(r.symbols) for r in reels],
            "weights_per_reel": reel_weights,
            "raw_strips": [r.symbols for r in reels]
        },
        "results": {
            "spins": result.spins,
            "total_bet": result.total_bet,
            "total_win": result.total_win,
            "rtp_percent": result.rtp,
            "hit_rate_percent": result.hit_rate,
            "hit_frequency": result.hit_frequency,
            "max_win": result.max_win,
            "max_win_x": result.max_win_x,
            "combinations": combs_list,
            "scatters": scatters_dict,
            "symbols": symbols_dict,
            "win_distribution": dict(result.statistics.win_distribution),
            "wild": {
                "landed": result.statistics.wild.landed,
                "spins_with_wild": result.statistics.wild.spins_with_wild,
                "wins_with_wild": result.statistics.wild.wins_with_wild,
                "win_amount_with_wild": result.statistics.wild.win_amount_with_wild,
                "expanded_cells": result.statistics.wild.expanded_cells,
                "boom_cells": result.statistics.wild.boom_cells
            }
        }
    }

    with open(filepath, mode="w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)