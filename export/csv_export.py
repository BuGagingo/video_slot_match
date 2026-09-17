import csv
from engine.simulator import SimulationResult


def export_simulation_to_csv(
    filepath: str,
    result: SimulationResult,
    reels: list,
    paytable: dict,
    payout_base: str = "TOTAL_BET",
    wild_config=None,
    scatter_config=None,
    game_name: str = "New Slot",
    total_bet: float = 1.0
):
    with open(filepath, mode="w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file, delimiter=";")

        # 1. Сводка игры
        writer.writerow([" SIMULATION SUMMARY "])
        writer.writerow(["Game Name", game_name])
        writer.writerow(["Payout Base Mode", payout_base])
        writer.writerow(["Spins", result.spins])
        writer.writerow(["Total Bet", f"{result.total_bet:.4f}"])
        writer.writerow(["Total Win", f"{result.total_win:.4f}"])
        writer.writerow(["RTP %", f"{result.rtp:.6f}"])
        writer.writerow(["Hit Rate %", f"{result.hit_rate:.6f}"])
        writer.writerow(["Hit Frequency", f"1 : {result.hit_frequency:.4f}"])
        writer.writerow(["Max Win", f"{result.max_win:.4f}"])
        writer.writerow(["Max Win X", f"{result.max_win_x:.4f}"])
        writer.writerow([])

        # 2. ТАБЛИЦА ВЫПЛАТ (PAYTABLE: Regular, Scatters, Bonus, Wild)
        writer.writerow([" PAYTABLE & SYMBOL MULTIPLIERS "])
        writer.writerow(["Symbol / Feature", "Type", "Payout Base", "x2", "x3", "x4", "x5", "Notes / Allowed Reels"])

        # Обычные символы на линиях
        base_desc = "Total Bet × Multiplier" if payout_base == "TOTAL_BET" else "Bet Per Line × Multiplier"
        for sym, pays in paytable.items():
            p2 = pays.get(2, pays.get("2", "-"))
            p3 = pays.get(3, pays.get("3", "-"))
            p4 = pays.get(4, pays.get("4", "-"))
            p5 = pays.get(5, pays.get("5", "-"))
            writer.writerow([sym, "Line Pay", base_desc, p2, p3, p4, p5, "Pays on active paylines from left to right (Reels: 1-5)"])

        # Скаттеры и Бонус
        if scatter_config:
            for idx, sc in enumerate(scatter_config.scatters):
                if not sc.enabled:
                    continue
                sc_type = f"Scatter {idx + 1}" if idx == 0 else "Bonus Scatter"
                p2 = sc.pays.get(2, sc.pays.get("2", "-"))
                p3 = sc.pays.get(3, sc.pays.get("3", "-"))
                p4 = sc.pays.get(4, sc.pays.get("4", "-"))
                p5 = sc.pays.get(5, sc.pays.get("5", "-"))
                reels_str = ", ".join(str(r + 1) for r in sc.allowed_reels)
                writer.writerow([sc.symbol_id, sc_type, "Total Bet × Multiplier", p2, p3, p4, p5, f"Pays anywhere on screen (Reels: {reels_str})"])

        # Wild
        if wild_config and wild_config.enabled:
            reels_str = ", ".join(str(r + 1) for r in wild_config.allowed_reels)
            wild_notes = [f"Reels: {reels_str}"]
            if wild_config.expanding_enabled:
                wild_notes.append("Expanding")
            if wild_config.sticky_enabled:
                wild_notes.append(f"Sticky ({wild_config.sticky_duration} spins)")
            if wild_config.boom_enabled:
                wild_notes.append(f"Boom (Radius: {wild_config.boom_radius})")
            writer.writerow([wild_config.symbol_id, "Wild Substitute", "-", "-", "-", "-", "-", "Substitutes regular symbols; " + ", ".join(wild_notes)])

        writer.writerow([])

        # 3. Веса и заполнение барабанов (Reel Weights)
        writer.writerow([" REEL STRIP WEIGHTS & DISTRIBUTION "])
        headers = ["Symbol"]
        for i in range(5):
            r_len = len(reels[i].symbols) if i < len(reels) else 0
            headers.extend([f"Reel {i+1} Count", f"Reel {i+1} % (Len: {r_len})"])
        headers.extend(["Total Count", "Avg %"])
        writer.writerow(headers)

        all_symbols = sorted(result.statistics.symbol_generated.keys())
        total_strip_symbols = sum(len(r.symbols) for r in reels)

        for sym in all_symbols:
            row = [sym]
            total_sym_cnt = 0
            for i in range(5):
                r_symbols = reels[i].symbols if i < len(reels) else []
                cnt = r_symbols.count(sym)
                pct = (cnt / len(r_symbols) * 100.0) if len(r_symbols) > 0 else 0.0
                total_sym_cnt += cnt
                row.extend([cnt, f"{pct:.4f} %"])
            avg_pct = (total_sym_cnt / total_strip_symbols * 100.0) if total_strip_symbols > 0 else 0.0
            row.extend([total_sym_cnt, f"{avg_pct:.4f} %"])
            writer.writerow(row)

        len_row = ["TOTAL LENGTH"]
        for i in range(5):
            r_len = len(reels[i].symbols) if i < len(reels) else 0
            len_row.extend([r_len, "100.0000 %"])
        len_row.extend([total_strip_symbols, "100.0000 %"])
        writer.writerow(len_row)
        writer.writerow([])

        # 4. Порядок символов на барабанах (Reel Sequences)
        writer.writerow([" REEL STRIP ORDER (SEQUENCE) "])
        writer.writerow(["Position", "Reel 1", "Reel 2", "Reel 3", "Reel 4", "Reel 5"])
        max_len = max(len(r.symbols) for r in reels) if reels else 0
        for pos in range(max_len):
            row = [pos + 1]
            for i in range(5):
                row.append(reels[i].symbols[pos] if pos < len(reels[i].symbols) else "")
            writer.writerow(row)
        writer.writerow([])

        # 5. Комбинации по линиям
        writer.writerow([" LINE COMBINATIONS "])
        writer.writerow(["Symbol", "Count", "Hits", "Hit %", "Total Win", "RTP Contribution %"])
        sorted_combs = sorted(result.statistics.combinations.items(), key=lambda x: (x[0][0], x[0][1]))
        for (sym, cnt), cstat in sorted_combs:
            hit_pct = (cstat.hits / result.spins * 100.0) if result.spins > 0 else 0.0
            rtp_cnt = (cstat.total_win / result.total_bet * 100.0) if result.total_bet > 0 else 0.0
            writer.writerow([sym, cnt, cstat.hits, f"{hit_pct:.6f}", f"{cstat.total_win:.4f}", f"{rtp_cnt:.6f}"])
        writer.writerow([])

        # 6. Скаттеры
        writer.writerow([" SCATTERS STATS "])
        writer.writerow(["Scatter", "Count on Screen", "Hits", "Frequency %", "Total Win", "RTP Contribution %"])
        for sc_sym, sc_stat in sorted(result.statistics.scatters.items()):
            for cnt, hits in sorted(sc_stat.hits_by_count.items()):
                if hits == 0:
                    continue
                hit_pct = (hits / result.spins * 100.0) if result.spins > 0 else 0.0
                mult = 0.0
                if scatter_config:
                    for sc in scatter_config.scatters:
                        if sc.symbol_id == sc_sym:
                            mult = sc.pays.get(cnt, 0.0)
                            break
                sc_win = hits * (total_bet * mult)
                rtp_cnt = (sc_win / result.total_bet * 100.0) if result.total_bet > 0 else 0.0
                writer.writerow([sc_sym, f"x{cnt}", hits, f"{hit_pct:.6f}", f"{sc_win:.4f}", f"{rtp_cnt:.6f}"])
        writer.writerow([])

        # 7. Символьная статистика в симуляции
        writer.writerow([" SYMBOLS SIMULATION HITS "])
        writer.writerow(["Symbol", "Generated Cells", "Frequency %", "Total Win", "RTP Contribution %"])
        total_gen = sum(result.statistics.symbol_generated.values())
        for sym in sorted(result.statistics.symbol_generated.keys()):
            gen = result.statistics.symbol_generated[sym]
            freq = (gen / total_gen * 100.0) if total_gen > 0 else 0.0
            s_stat = result.statistics.symbols.get(sym)
            win = s_stat.total_win if s_stat else 0.0
            rtp_cnt = (win / result.total_bet * 100.0) if result.total_bet > 0 else 0.0
            writer.writerow([sym, gen, f"{freq:.6f}", f"{win:.4f}", f"{rtp_cnt:.6f}"])
        writer.writerow([])

        # 8. Распределение выигрышей
        writer.writerow([" WIN DISTRIBUTION "])
        writer.writerow(["Bucket", "Spins", "Frequency %"])
        order = ["0x", "0-1x", "1-2x", "2-5x", "5-10x", "10-20x", "20-50x", "50-100x", "100-500x", "500-1000x", "1000x+"]
        for b in order:
            cnt = result.statistics.win_distribution.get(b, 0)
            pct = (cnt / result.spins * 100.0) if result.spins > 0 else 0.0
            writer.writerow([b, cnt, f"{pct:.6f}"])
        writer.writerow([])

        # 9. Wild статистика
        writer.writerow([" WILD STATISTICS "])
        w = result.statistics.wild
        w_freq = (result.spins / w.spins_with_wild) if w.spins_with_wild > 0 else 0.0
        w_rtp = (w.win_amount_with_wild / result.total_bet * 100.0) if result.total_bet > 0 else 0.0
        writer.writerow(["Wild Landed", w.landed])
        writer.writerow(["Spins with Wild", w.spins_with_wild])
        writer.writerow(["Wild Spin Frequency", f"1 : {w_freq:.4f}" if w_freq > 0 else "-"])
        writer.writerow(["Expanded Cells", w.expanded_cells])
        writer.writerow(["Boom Cells", w.boom_cells])
        writer.writerow(["Winning Lines with Wild", w.wins_with_wild])
        writer.writerow(["Win Amount with Wild", f"{w.win_amount_with_wild:.4f}"])
        writer.writerow(["Wild RTP Contribution %", f"{w_rtp:.6f}"])