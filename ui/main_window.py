import os
import json
import time
import gc
import random
from concurrent.futures import ProcessPoolExecutor, as_completed

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QGridLayout,
    QMessageBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QFormLayout,
    QCheckBox,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QFileDialog,
    QMenu
)

from engine.reel import Reel
from engine.simulator import SlotSimulator, run_simulation_worker_task, SimulationResult
from engine.rng import RNGAlgorithm, generate_time_seed
from data.lines_53 import lines as lines_53
from data.lines_54 import lines as lines_54
from engine.validator import ModelValidator
from features.wild import WildConfig
from features.scatter import ScatterConfig, SingleScatterConfig
from export.csv_export import export_simulation_to_csv
from export.json_export import export_simulation_to_json


AUTOSAVE_FILENAME = "autosave_config.json"


class AsyncSimulationWorker(QThread):
    progress_signal = Signal(int, int, int)
    finished_signal = Signal(object)
    error_signal = Signal(str)

    def __init__(self, simulation_params: dict):
        super().__init__()
        self.params = simulation_params
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            total_spins = self.params["spins"]
            rows = self.params["rows"]

            total_cores = os.cpu_count() or 2
            max_workers = max(1, total_cores - 1) if total_cores > 2 else total_cores

            wave_limit = 100_000
            chunk_size = max(5_000, wave_limit // (max_workers * 2))

            merged_result = None
            done_spins = 0
            remaining_spins = total_spins
            base_seed = self.params.get("seed")
            task_idx = 0

            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                while remaining_spins > 0 and not self._is_cancelled:
                    current_wave_spins = min(remaining_spins, wave_limit)
                    wave_remaining = current_wave_spins

                    tasks = []
                    while wave_remaining > 0:
                        spins_for_task = min(wave_remaining, chunk_size)

                        if base_seed is not None:
                            task_seed = (base_seed + task_idx * 1_000_003) % (2**63 - 1)
                        else:
                            task_seed = generate_time_seed()

                        tasks.append({
                            "reels": self.params["reels"],
                            "paylines": self.params["paylines"],
                            "paytable": self.params["paytable"],
                            "total_bet": self.params["total_bet"],
                            "payout_base": self.params["payout_base"],
                            "bet_per_line": self.params["bet_per_line"],
                            "wild_config": self.params["wild_config"],
                            "scatter_config": self.params["scatter_config"],
                            "rng_algorithm": self.params["rng_algorithm"],
                            "rows": rows,
                            "spins": spins_for_task,
                            "seed": task_seed
                        })
                        wave_remaining -= spins_for_task
                        task_idx += 1

                    futures = [executor.submit(run_simulation_worker_task, t) for t in tasks]

                    for f in as_completed(futures):
                        if self._is_cancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            return

                        chunk_result: SimulationResult = f.result()
                        if merged_result is None:
                            merged_result = chunk_result
                        else:
                            merged_result.merge(chunk_result)

                        done_spins += chunk_result.spins
                        percent = int((done_spins / total_spins) * 100)
                        self.progress_signal.emit(percent, done_spins, total_spins)

                    remaining_spins -= current_wave_spins

                    if remaining_spins > 0 and not self._is_cancelled:
                        gc.collect()
                        time.sleep(0.08)

            if not self._is_cancelled and merged_result is not None:
                self.finished_signal.emit(merged_result)

        except Exception as exc:
            if not self._is_cancelled:
                self.error_signal.emit(str(exc))


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Slot Math Designer")
        self.resize(1340, 780)

        self.last_simulation_result: SimulationResult | None = None
        self.simulation_worker = None

        self.build_ui()

        if os.path.exists(AUTOSAVE_FILENAME):
            try:
                self.load_config_from_file(AUTOSAVE_FILENAME, show_msg=False)
            except Exception:
                self.load_default_symbols()
        else:
            self.load_default_symbols()

        self.reload_paylines()
        self.update_grid_preview()
        self.update_reel_distribution()

    def closeEvent(self, event):
        try:
            self.save_config_to_file(AUTOSAVE_FILENAME, show_msg=False)
        except Exception:
            pass
        event.accept()

    # =====================================================
    # BUILD UI
    # =====================================================

    def build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # ----------------- TOP TOOLBAR -----------------
        top_bar = QHBoxLayout()

        self.project_menu_btn = QPushButton("📁 Project / Config ▼")
        self.project_menu_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 6px 14px; }")
        project_menu = QMenu(self)

        act_save = QAction("💾 Save Config As Preset...", self)
        act_save.triggered.connect(self.action_save_preset)
        project_menu.addAction(act_save)

        act_load = QAction("📂 Open Saved Preset...", self)
        act_load.triggered.connect(self.action_load_preset)
        project_menu.addAction(act_load)

        project_menu.addSeparator()

        act_reset = QAction("🔄 Reset to Default Configuration", self)
        act_reset.triggered.connect(self.action_reset_defaults)
        project_menu.addAction(act_reset)

        self.project_menu_btn.setMenu(project_menu)
        top_bar.addWidget(self.project_menu_btn)

        self.export_menu_btn = QPushButton("📤 Export Data ▼")
        self.export_menu_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 6px 14px; }")
        export_menu = QMenu(self)

        act_exp_csv = QAction("📊 Export Complete Statistics to CSV (.csv)", self)
        act_exp_csv.triggered.connect(self.action_export_csv)
        export_menu.addAction(act_exp_csv)

        act_exp_json = QAction("🗄️ Export Full Model & Results to JSON (.json)", self)
        act_exp_json.triggered.connect(self.action_export_json)
        export_menu.addAction(act_exp_json)

        act_exp_png = QAction("🖼️ Export Window Screenshot to PNG (.png)", self)
        act_exp_png.triggered.connect(self.action_export_png)
        export_menu.addAction(act_exp_png)

        self.export_menu_btn.setMenu(export_menu)
        top_bar.addWidget(self.export_menu_btn)

        top_bar.addStretch()

        self.status_preset_label = QLabel("Auto-save Active")
        self.status_preset_label.setStyleSheet("color: #888; font-style: italic; font-size: 12px;")
        top_bar.addWidget(self.status_preset_label)

        main_layout.addLayout(top_bar)

        # ----------------- THREE-COLUMN BODY -----------------
        root_layout = QHBoxLayout()

        # 1. LEFT: Statistics
        statistics_box = QGroupBox("Statistics")
        statistics_layout = QVBoxLayout(statistics_box)

        self.spins_label = QLabel("Spins: 0")
        self.total_bet_label = QLabel("Total Bet: 0")
        self.total_win_label = QLabel("Total Win: 0")
        self.rtp_label = QLabel("RTP: 0.000000 %")
        self.hit_rate_label = QLabel("Hit Rate: 0.000000 %")
        self.hit_frequency_label = QLabel("Hit Frequency: 1 : 0")
        self.max_win_label = QLabel("Max Win: 0")
        self.max_win_x_label = QLabel("Max Win X: 0.0000 x")

        labels = [
            self.spins_label,
            self.total_bet_label,
            self.total_win_label,
            self.rtp_label,
            self.hit_rate_label,
            self.hit_frequency_label,
            self.max_win_label,
            self.max_win_x_label
        ]

        for label in labels:
            label.setStyleSheet("QLabel { font-size: 14px; padding: 3px; }")
            statistics_layout.addWidget(label)

        statistics_layout.addStretch()
        root_layout.addWidget(statistics_box, 2)

        # 2. CENTER: Game Preview & Progress
        center_box = QGroupBox("Game Preview")
        center_layout = QVBoxLayout(center_box)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        center_layout.addWidget(self.grid_widget)

        self.single_spin_button = QPushButton("SPIN ONCE")
        self.single_spin_button.setMinimumHeight(38)
        self.single_spin_button.clicked.connect(self.run_single_spin)
        center_layout.addWidget(self.single_spin_button)

        btn_action_layout = QHBoxLayout()
        safe_cores = max(1, (os.cpu_count() or 2) - 1)
        self.run_button = QPushButton(f"RUN SIMULATION ({safe_cores} Cores)")
        self.run_button.setMinimumHeight(45)
        self.run_button.setStyleSheet("QPushButton { font-weight: bold; font-size: 13px; }")
        self.run_button.clicked.connect(self.run_simulation)
        btn_action_layout.addWidget(self.run_button)

        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setMinimumHeight(45)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_simulation)
        btn_action_layout.addWidget(self.cancel_button)

        center_layout.addLayout(btn_action_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                height: 22px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2e7d32;
            }
            """
        )
        center_layout.addWidget(self.progress_bar)

        self.progress_info_label = QLabel("Ready")
        self.progress_info_label.setAlignment(Qt.AlignCenter)
        self.progress_info_label.setStyleSheet("color: #aaa; font-size: 12px;")
        center_layout.addWidget(self.progress_info_label)

        root_layout.addWidget(center_box, 5)

        # 3. RIGHT: Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_game_tab(), "GAME")
        self.tabs.addTab(self.create_symbols_tab(), "SYMBOLS")
        self.tabs.addTab(self.create_paytable_tab(), "PAYTABLE")
        self.tabs.addTab(self.create_reels_tab(), "REELS")
        self.tabs.addTab(self.create_paylines_tab(), "PAYLINES")
        self.tabs.addTab(self.create_wild_tab(), "WILD")
        self.tabs.addTab(self.create_scatters_tab(), "SCATTERS")
        self.tabs.addTab(self.create_statistics_tab(), "STATISTICS")

        root_layout.addWidget(self.tabs, 5)
        main_layout.addLayout(root_layout)

    # =====================================================
    # PRESETS & CONFIG
    # =====================================================

    def get_full_config_dict(self) -> dict:
        rng_algo, seed = self.get_rng_config()
        symbols = []
        for r in range(self.symbols_table.rowCount()):
            sym_id = self.symbols_table.item(r, 0).text() if self.symbols_table.item(r, 0) else ""
            sym_name = self.symbols_table.item(r, 1).text() if self.symbols_table.item(r, 1) else ""
            if sym_id:
                symbols.append({"id": sym_id, "name": sym_name})

        reels = [
            [s.strip() for s in ed.toPlainText().splitlines() if s.strip()]
            for ed in self.reel_editors
        ]

        wild_cfg = self.get_wild_config()
        scatter_cfg = self.get_scatter_config()

        return {
            "game_name": self.game_name_edit.text(),
            "field": self.field_combo.currentText(),
            "active_lines": self.lines_spin.value(),
            "payout_base": self.payout_base_combo.currentData(),
            "total_bet": self.total_bet_spin.value(),
            "simulation_spins": self.simulation_spins.value(),
            "rng": {
                "algorithm": rng_algo,
                "seed_mode": self.seed_mode_combo.currentData(),
                "custom_seed": self.custom_seed_spin.value()
            },
            "symbols": symbols,
            "paytable": self.get_paytable(),
            "reels": reels,
            "wild": {
                "enabled": wild_cfg.enabled,
                "symbol_id": wild_cfg.symbol_id,
                "allowed_reels": wild_cfg.allowed_reels,
                "expanding_enabled": wild_cfg.expanding_enabled,
                "sticky_enabled": wild_cfg.sticky_enabled,
                "sticky_duration": wild_cfg.sticky_duration,
                "boom_enabled": wild_cfg.boom_enabled,
                "boom_radius": wild_cfg.boom_radius,
                "boom_diagonal": wild_cfg.boom_diagonal
            },
            "scatters": [
                {
                    "enabled": sc.enabled,
                    "symbol_id": sc.symbol_id,
                    "allowed_reels": sc.allowed_reels,
                    "pays": sc.pays
                }
                for sc in scatter_cfg.scatters
            ]
        }

    def apply_config_dict(self, config: dict):
        if "game_name" in config:
            self.game_name_edit.setText(config["game_name"])
        if "field" in config:
            self.field_combo.setCurrentText(config["field"])
        if "active_lines" in config:
            self.lines_spin.setValue(config["active_lines"])
        if "payout_base" in config:
            idx = self.payout_base_combo.findData(config["payout_base"])
            if idx >= 0:
                self.payout_base_combo.setCurrentIndex(idx)
        if "total_bet" in config:
            self.total_bet_spin.setValue(config["total_bet"])
        if "simulation_spins" in config:
            self.simulation_spins.setValue(config["simulation_spins"])

        # RNG
        if "rng" in config:
            rng_c = config["rng"]
            idx = self.rng_algo_combo.findData(rng_c.get("algorithm", RNGAlgorithm.PCG64))
            if idx >= 0:
                self.rng_algo_combo.setCurrentIndex(idx)
            s_mode = rng_c.get("seed_mode", "TIME")
            idx2 = self.seed_mode_combo.findData(s_mode)
            if idx2 >= 0:
                self.seed_mode_combo.setCurrentIndex(idx2)
            self.custom_seed_spin.setValue(rng_c.get("custom_seed", 123456))

        # Symbols
        if "symbols" in config:
            self.symbols_table.setRowCount(0)
            for item in config["symbols"]:
                row = self.symbols_table.rowCount()
                self.symbols_table.insertRow(row)
                self.symbols_table.setItem(row, 0, QTableWidgetItem(item["id"]))
                self.symbols_table.setItem(row, 1, QTableWidgetItem(item["name"]))

        # Paytable
        self.refresh_paytable()
        if "paytable" in config:
            for row in range(self.paytable_table.rowCount()):
                sym_item = self.paytable_table.item(row, 0)
                if not sym_item:
                    continue
                sym_id = sym_item.text()
                if sym_id in config["paytable"]:
                    pays = config["paytable"][sym_id]
                    for col_idx, count in enumerate([2, 3, 4, 5]):
                        if count in pays or str(count) in pays:
                            val = pays.get(count, pays.get(str(count), 0.0))
                            self.paytable_table.setItem(row, col_idx + 1, QTableWidgetItem(str(val)))

        # Reels
        if "reels" in config and len(config["reels"]) == 5:
            for i in range(5):
                self.reel_editors[i].setPlainText("\n".join(config["reels"][i]))
                if hasattr(self, "reel_gen_spins"):
                    self.reel_gen_spins[i].setValue(len(config["reels"][i]))

        # Wild
        if "wild" in config:
            wc = config["wild"]
            self.wild_enabled.setChecked(wc.get("enabled", True))
            self.wild_symbol_edit.setText(wc.get("symbol_id", "WILD"))
            for i, chk in enumerate(self.wild_reel_checks):
                chk.setChecked(i in wc.get("allowed_reels", [1, 2, 3]))
            self.expanding_enabled.setChecked(wc.get("expanding_enabled", False))
            self.sticky_enabled.setChecked(wc.get("sticky_enabled", False))
            self.sticky_duration.setValue(wc.get("sticky_duration", 3))
            self.boom_enabled.setChecked(wc.get("boom_enabled", False))
            self.boom_radius.setValue(wc.get("boom_radius", 1))
            self.boom_diagonal.setChecked(wc.get("boom_diagonal", True))

        # Scatters
        if "scatters" in config and len(config["scatters"]) >= 1:
            sc1 = config["scatters"][0]
            self.sc1_enabled.setChecked(sc1.get("enabled", False))
            self.sc1_symbol_edit.setText(sc1.get("symbol_id", "SCATTER"))
            for i, chk in enumerate(self.sc1_reel_checks):
                chk.setChecked(i in sc1.get("allowed_reels", [0, 1, 2, 3, 4]))
            for count, spin in self.sc1_pays.items():
                spin.setValue(sc1.get("pays", {}).get(str(count), sc1.get("pays", {}).get(count, 0.0)))

        if "scatters" in config and len(config["scatters"]) >= 2:
            sc2 = config["scatters"][1]
            self.sc2_enabled.setChecked(sc2.get("enabled", False))
            self.sc2_symbol_edit.setText(sc2.get("symbol_id", "BONUS"))
            for i, chk in enumerate(self.sc2_reel_checks):
                chk.setChecked(i in sc2.get("allowed_reels", [0, 2, 4]))
            for count, spin in self.sc2_pays.items():
                spin.setValue(sc2.get("pays", {}).get(str(count), sc2.get("pays", {}).get(count, 0.0)))

        self.reload_paylines()
        self.update_grid_preview()
        self.update_reel_distribution()

    def save_config_to_file(self, filepath: str, show_msg: bool = True):
        cfg = self.get_full_config_dict()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        if show_msg:
            QMessageBox.information(self, "Preset Saved", f"Configuration successfully saved to:\n{filepath}")

    def load_config_from_file(self, filepath: str, show_msg: bool = True):
        with open(filepath, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.apply_config_dict(cfg)
        if show_msg:
            QMessageBox.information(self, "Preset Loaded", f"Configuration loaded from:\n{filepath}")

    def action_save_preset(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Save Preset As", "", "Slot Presets (*.json *.slot)")
        if filepath:
            if not filepath.endswith(".json") and not filepath.endswith(".slot"):
                filepath += ".json"
            self.save_config_to_file(filepath)

    def action_load_preset(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Open Preset", "", "Slot Presets (*.json *.slot);;All Files (*)")
        if filepath:
            try:
                self.load_config_from_file(filepath)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load preset:\n{str(e)}")

    def action_reset_defaults(self):
        if QMessageBox.question(self, "Reset", "Reset all parameters to default values?") == QMessageBox.Yes:
            self.load_default_symbols()
            self.reload_paylines()
            self.update_grid_preview()

    # =====================================================
    # EXPORT ACTIONS
    # =====================================================

    def action_export_csv(self):
        if not self.last_simulation_result:
            QMessageBox.information(self, "No Data", "Please run a simulation first to export statistics.")
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "Export Complete Statistics to CSV", "simulation_full_report.csv", "CSV Files (*.csv)")
        if filepath:
            try:
                export_simulation_to_csv(
                    filepath=filepath,
                    result=self.last_simulation_result,
                    reels=self.get_reels(),
                    paytable=self.get_paytable(),
                    payout_base=self.payout_base_combo.currentData(),
                    wild_config=self.get_wild_config(),
                    scatter_config=self.get_scatter_config(),
                    game_name=self.game_name_edit.text(),
                    total_bet=self.total_bet_spin.value()
                )
                QMessageBox.information(self, "Export Complete", f"CSV report exported to:\n{filepath}")
            except Exception as err:
                QMessageBox.critical(self, "Export Error", str(err))

    def action_export_json(self):
        if not self.last_simulation_result:
            QMessageBox.information(self, "No Data", "Please run a simulation first to export results.")
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "Export to JSON", "simulation_result.json", "JSON Files (*.json)")
        if filepath:
            try:
                export_simulation_to_json(
                    filepath=filepath,
                    result=self.last_simulation_result,
                    config_dict=self.get_full_config_dict(),
                    reels=self.get_reels()
                )
                QMessageBox.information(self, "Export Complete", f"JSON data exported to:\n{filepath}")
            except Exception as err:
                QMessageBox.critical(self, "Export Error", str(err))

    def action_export_png(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Export Window Screenshot", "slot_math_screenshot.png", "PNG Images (*.png)")
        if filepath:
            pixmap = self.grab()
            if pixmap.save(filepath, "PNG"):
                QMessageBox.information(self, "Export Complete", f"Screenshot saved to:\n{filepath}")
            else:
                QMessageBox.critical(self, "Export Error", "Failed to save image.")

    # =====================================================
    # GAME TAB
    # =====================================================

    def create_game_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QFormLayout(widget)

        self.game_name_edit = QLineEdit("New Slot")
        layout.addRow("Game Name:", self.game_name_edit)

        self.field_combo = QComboBox()
        self.field_combo.addItems(["5x3", "5x4"])
        self.field_combo.currentTextChanged.connect(self.on_field_size_changed)
        layout.addRow("Field:", self.field_combo)

        self.lines_spin = QSpinBox()
        self.lines_spin.setRange(1, 1024)
        self.lines_spin.setValue(20)
        self.lines_spin.valueChanged.connect(self.reload_paylines)
        self.lines_spin.valueChanged.connect(self.update_bet_information)
        layout.addRow("Active Paylines:", self.lines_spin)

        self.payout_base_combo = QComboBox()
        self.payout_base_combo.addItem("Total Bet", "TOTAL_BET")
        self.payout_base_combo.addItem("Bet Per Line", "BET_PER_LINE")
        layout.addRow("Payout Base:", self.payout_base_combo)

        self.total_bet_spin = QDoubleSpinBox()
        self.total_bet_spin.setRange(0.01, 1_000_000_000)
        self.total_bet_spin.setDecimals(4)
        self.total_bet_spin.setValue(1.0)
        self.total_bet_spin.valueChanged.connect(self.update_bet_information)
        layout.addRow("Total Bet:", self.total_bet_spin)

        self.simulation_spins = QSpinBox()
        self.simulation_spins.setRange(1, 100_000_000)
        self.simulation_spins.setValue(100_000)
        layout.addRow("Simulation Spins:", self.simulation_spins)

        self.calculated_bet_per_line_label = QLabel("0.050000")
        layout.addRow("Calculated Bet / Line:", self.calculated_bet_per_line_label)

        # RNG
        rng_box = QGroupBox("RNG Settings (ГСЧ)")
        rng_layout = QFormLayout(rng_box)

        self.rng_algo_combo = QComboBox()
        self.rng_algo_combo.addItem("PCG64 (Fast & High Quality)", RNGAlgorithm.PCG64)
        self.rng_algo_combo.addItem("Mersenne Twister (MT19937)", RNGAlgorithm.MT19937)
        self.rng_algo_combo.addItem("Philox (Parallel / Counter-based)", RNGAlgorithm.PHILOX)
        self.rng_algo_combo.addItem("SFC64 (Small Fast Chaotic)", RNGAlgorithm.SFC64)
        rng_layout.addRow("RNG Algorithm:", self.rng_algo_combo)

        self.seed_mode_combo = QComboBox()
        self.seed_mode_combo.addItem("Auto / Time-based (По времени)", "TIME")
        self.seed_mode_combo.addItem("Fixed Seed (Фиксированный)", "FIXED")
        self.seed_mode_combo.currentIndexChanged.connect(self.toggle_seed_input)
        rng_layout.addRow("Seed Mode:", self.seed_mode_combo)

        self.custom_seed_spin = QSpinBox()
        self.custom_seed_spin.setRange(0, 2_000_000_000)
        self.custom_seed_spin.setValue(123456)
        self.custom_seed_spin.setEnabled(False)
        rng_layout.addRow("Custom Seed:", self.custom_seed_spin)

        layout.addRow(rng_box)

        scroll.setWidget(widget)
        return scroll

    def toggle_seed_input(self):
        is_fixed = (self.seed_mode_combo.currentData() == "FIXED")
        self.custom_seed_spin.setEnabled(is_fixed)

    def get_rng_config(self) -> tuple[str, int | None]:
        algo = self.rng_algo_combo.currentData()
        mode = self.seed_mode_combo.currentData()
        seed = self.custom_seed_spin.value() if mode == "FIXED" else None
        return algo, seed

    def on_field_size_changed(self):
        self.update_grid_preview()
        self.reload_paylines()

    # =====================================================
    # WILD TAB
    # =====================================================

    def create_wild_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        basic_box = QGroupBox("Wild")
        basic_layout = QVBoxLayout(basic_box)

        self.wild_enabled = QCheckBox("Enable Wild")
        basic_layout.addWidget(self.wild_enabled)

        self.wild_symbol_edit = QLineEdit("WILD")
        basic_layout.addWidget(QLabel("Wild Symbol ID:"))
        basic_layout.addWidget(self.wild_symbol_edit)

        basic_layout.addWidget(QLabel("Allowed Reels:"))
        self.wild_reel_checks = []
        reel_layout = QHBoxLayout()
        for index in range(5):
            checkbox = QCheckBox(str(index + 1))
            if index in [1, 2, 3]:
                checkbox.setChecked(True)
            self.wild_reel_checks.append(checkbox)
            reel_layout.addWidget(checkbox)
        basic_layout.addLayout(reel_layout)
        layout.addWidget(basic_box)

        expanding_box = QGroupBox("Expanding")
        expanding_layout = QVBoxLayout(expanding_box)
        self.expanding_enabled = QCheckBox("Expand vertically to full reel")
        expanding_layout.addWidget(self.expanding_enabled)
        layout.addWidget(expanding_box)

        sticky_box = QGroupBox("Sticky")
        sticky_layout = QFormLayout(sticky_box)
        self.sticky_enabled = QCheckBox("Enable Sticky Wild")
        sticky_layout.addRow(self.sticky_enabled)
        self.sticky_duration = QSpinBox()
        self.sticky_duration.setRange(1, 100)
        self.sticky_duration.setValue(3)
        sticky_layout.addRow("Duration Spins:", self.sticky_duration)
        layout.addWidget(sticky_box)

        boom_box = QGroupBox("Boom")
        boom_layout = QFormLayout(boom_box)
        self.boom_enabled = QCheckBox("Enable Boom")
        boom_layout.addRow(self.boom_enabled)
        self.boom_radius = QSpinBox()
        self.boom_radius.setRange(1, 5)
        self.boom_radius.setValue(1)
        boom_layout.addRow("Radius:", self.boom_radius)
        self.boom_diagonal = QCheckBox("Include diagonal cells")
        self.boom_diagonal.setChecked(True)
        boom_layout.addRow(self.boom_diagonal)
        layout.addWidget(boom_box)

        layout.addStretch()
        return widget

    def get_wild_config(self):
        allowed_reels = [
            idx for idx, chk in enumerate(self.wild_reel_checks) if chk.isChecked()
        ]
        return WildConfig(
            enabled=self.wild_enabled.isChecked(),
            symbol_id=self.wild_symbol_edit.text().strip() or "WILD",
            allowed_reels=allowed_reels,
            expanding_enabled=self.expanding_enabled.isChecked(),
            sticky_enabled=self.sticky_enabled.isChecked(),
            sticky_duration=self.sticky_duration.value(),
            boom_enabled=self.boom_enabled.isChecked(),
            boom_radius=self.boom_radius.value(),
            boom_diagonal=self.boom_diagonal.isChecked()
        )

    # =====================================================
    # SCATTERS TAB
    # =====================================================

    def create_scatters_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Scatter 1
        sc1_box = QGroupBox("Scatter 1 (Main Scatter)")
        sc1_layout = QVBoxLayout(sc1_box)

        self.sc1_enabled = QCheckBox("Enable Scatter 1")
        sc1_layout.addWidget(self.sc1_enabled)

        self.sc1_symbol_edit = QLineEdit("SCATTER")
        sc1_layout.addWidget(QLabel("Symbol ID:"))
        sc1_layout.addWidget(self.sc1_symbol_edit)

        sc1_layout.addWidget(QLabel("Allowed Reels:"))
        self.sc1_reel_checks = []
        sc1_reel_layout = QHBoxLayout()
        for idx in range(5):
            chk = QCheckBox(str(idx + 1))
            chk.setChecked(True)
            self.sc1_reel_checks.append(chk)
            sc1_reel_layout.addWidget(chk)
        sc1_layout.addLayout(sc1_reel_layout)

        sc1_layout.addWidget(QLabel("Scatter Payout (Total Bet × Multiplier):"))
        self.sc1_pays = {}
        sc1_pay_layout = QGridLayout()
        for i, count in enumerate([2, 3, 4, 5]):
            sc1_pay_layout.addWidget(QLabel(f"x{count}:"), 0, i * 2)
            spin = QDoubleSpinBox()
            spin.setRange(0, 100_000)
            spin.setDecimals(2)
            spin.setValue([0.0, 2.0, 10.0, 50.0][i])
            self.sc1_pays[count] = spin
            sc1_pay_layout.addWidget(spin, 0, i * 2 + 1)
        sc1_layout.addLayout(sc1_pay_layout)
        layout.addWidget(sc1_box)

        # Scatter 2
        sc2_box = QGroupBox("Scatter 2 (Bonus Scatter)")
        sc2_layout = QVBoxLayout(sc2_box)

        self.sc2_enabled = QCheckBox("Enable Scatter 2")
        sc2_layout.addWidget(self.sc2_enabled)

        self.sc2_symbol_edit = QLineEdit("BONUS")
        sc2_layout.addWidget(QLabel("Symbol ID:"))
        sc2_layout.addWidget(self.sc2_symbol_edit)

        sc2_layout.addWidget(QLabel("Allowed Reels:"))
        self.sc2_reel_checks = []
        sc2_reel_layout = QHBoxLayout()
        for idx in range(5):
            chk = QCheckBox(str(idx + 1))
            if idx in [0, 2, 4]:
                chk.setChecked(True)
            self.sc2_reel_checks.append(chk)
            sc2_reel_layout.addWidget(chk)
        sc2_layout.addLayout(sc2_reel_layout)

        sc2_layout.addWidget(QLabel("Scatter Payout (Total Bet × Multiplier):"))
        self.sc2_pays = {}
        sc2_pay_layout = QGridLayout()
        for i, count in enumerate([2, 3, 4, 5]):
            sc2_pay_layout.addWidget(QLabel(f"x{count}:"), 0, i * 2)
            spin = QDoubleSpinBox()
            spin.setRange(0, 100_000)
            spin.setDecimals(2)
            spin.setValue([0.0, 5.0, 25.0, 150.0][i])
            self.sc2_pays[count] = spin
            sc2_pay_layout.addWidget(spin, 0, i * 2 + 1)
        sc2_layout.addLayout(sc2_pay_layout)
        layout.addWidget(sc2_box)

        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def get_scatter_config(self) -> ScatterConfig:
        scatters = []

        sc1_reels = [idx for idx, chk in enumerate(self.sc1_reel_checks) if chk.isChecked()]
        sc1_pays = {cnt: spin.value() for cnt, spin in self.sc1_pays.items() if spin.value() > 0}
        scatters.append(
            SingleScatterConfig(
                enabled=self.sc1_enabled.isChecked(),
                symbol_id=self.sc1_symbol_edit.text().strip() or "SCATTER",
                allowed_reels=sc1_reels,
                pays=sc1_pays
            )
        )

        sc2_reels = [idx for idx, chk in enumerate(self.sc2_reel_checks) if chk.isChecked()]
        sc2_pays = {cnt: spin.value() for cnt, spin in self.sc2_pays.items() if spin.value() > 0}
        scatters.append(
            SingleScatterConfig(
                enabled=self.sc2_enabled.isChecked(),
                symbol_id=self.sc2_symbol_edit.text().strip() or "BONUS",
                allowed_reels=sc2_reels,
                pays=sc2_pays
            )
        )

        return ScatterConfig(scatters=scatters)

    # =====================================================
    # STATISTICS TAB
    # =====================================================

    def create_statistics_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.statistics_tabs = QTabWidget()

        # Combinations
        self.combination_table = QTableWidget(0, 6)
        self.combination_table.setHorizontalHeaderLabels(
            ["Symbol", "Count", "Hits", "Hit %", "Total Win", "RTP %"]
        )
        self.combination_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.statistics_tabs.addTab(self.combination_table, "Combinations")

        # Scatters
        self.scatter_statistics_table = QTableWidget(0, 6)
        self.scatter_statistics_table.setHorizontalHeaderLabels(
            ["Scatter", "Count on Field", "Hits", "Frequency %", "Total Win", "RTP %"]
        )
        self.scatter_statistics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.statistics_tabs.addTab(self.scatter_statistics_table, "Scatters")

        # Symbols tab (with 2 tables: General Summary + Reel Weights)
        symbols_tab_widget = QWidget()
        symbols_tab_layout = QVBoxLayout(symbols_tab_widget)

        symbols_tab_layout.addWidget(QLabel("<b>Symbol Wins & Frequency Summary:</b>"))
        self.symbol_statistics_table = QTableWidget(0, 5)
        self.symbol_statistics_table.setHorizontalHeaderLabels(
            ["Symbol", "Generated", "Frequency %", "Win", "RTP %"]
        )
        self.symbol_statistics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        symbols_tab_layout.addWidget(self.symbol_statistics_table, 1)

        symbols_tab_layout.addWidget(QLabel("<b>Reel Strip Weights & Distribution (Count / % on Reel):</b>"))
        self.symbol_reels_table = QTableWidget(0, 6)
        self.symbol_reels_table.setHorizontalHeaderLabels(
            ["Symbol", "Reel 1", "Reel 2", "Reel 3", "Reel 4", "Reel 5"]
        )
        self.symbol_reels_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        symbols_tab_layout.addWidget(self.symbol_reels_table, 1)

        self.statistics_tabs.addTab(symbols_tab_widget, "Symbols")

        # Distribution
        self.win_distribution_table = QTableWidget(0, 3)
        self.win_distribution_table.setHorizontalHeaderLabels(
            ["Win Range", "Spins", "Frequency %"]
        )
        self.win_distribution_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.statistics_tabs.addTab(self.win_distribution_table, "Distribution")

        # Wild
        self.wild_statistics_table = QTableWidget(0, 2)
        self.wild_statistics_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.wild_statistics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.statistics_tabs.addTab(self.wild_statistics_table, "Wild")

        layout.addWidget(self.statistics_tabs)
        return widget

    # =====================================================
    # SYMBOLS & PAYTABLE
    # =====================================================

    def create_symbols_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.symbols_table = QTableWidget(0, 2)
        self.symbols_table.setHorizontalHeaderLabels(["ID", "Name"])
        self.symbols_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.symbols_table)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Symbol")
        rem_btn = QPushButton("Remove")
        add_btn.clicked.connect(self.add_symbol)
        rem_btn.clicked.connect(self.remove_symbol)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(rem_btn)
        layout.addLayout(btn_layout)

        return widget

    def create_paytable_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.paytable_table = QTableWidget(0, 5)
        self.paytable_table.setHorizontalHeaderLabels(["Symbol", "x2", "x3", "x4", "x5"])
        self.paytable_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.paytable_table)

        refresh_btn = QPushButton("Refresh From Symbols")
        refresh_btn.clicked.connect(self.refresh_paytable)
        layout.addWidget(refresh_btn)

        self.paytable_info = QLabel()
        self.paytable_info.setWordWrap(True)
        layout.addWidget(self.paytable_info)

        self.payout_base_combo.currentIndexChanged.connect(self.update_paytable_info)
        self.update_paytable_info()

        return widget

    def update_paytable_info(self):
        mode = self.payout_base_combo.currentData()
        if mode == "TOTAL_BET":
            text = (
                "Paytable values are MULTIPLIERS.\n"
                "Formula: Total Bet × Multiplier.\n"
                "Example: 10.00 × 0.3 = 3.00"
            )
        else:
            text = (
                "Paytable values are MULTIPLIERS.\n"
                "Formula: Bet Per Line × Multiplier.\n"
                "Example: 0.50 × 0.3 = 0.15"
            )
        self.paytable_info.setText(text)

    def load_default_symbols(self):
        default_symbols = [
            ("A", "Ace"),
            ("K", "King"),
            ("Q", "Queen"),
            ("J", "Jack"),
            ("10", "Ten"),
            ("7", "Seven")
        ]
        self.symbols_table.setRowCount(0)
        for symbol_id, name in default_symbols:
            row = self.symbols_table.rowCount()
            self.symbols_table.insertRow(row)
            self.symbols_table.setItem(row, 0, QTableWidgetItem(symbol_id))
            self.symbols_table.setItem(row, 1, QTableWidgetItem(name))

        self.refresh_paytable()
        self.load_example_reels()

    def add_symbol(self):
        row = self.symbols_table.rowCount()
        self.symbols_table.insertRow(row)
        self.symbols_table.setItem(row, 0, QTableWidgetItem("NEW"))
        self.symbols_table.setItem(row, 1, QTableWidgetItem("New Symbol"))

    def remove_symbol(self):
        row = self.symbols_table.currentRow()
        if row >= 0:
            self.symbols_table.removeRow(row)

    def refresh_paytable(self):
        existing_values = {}
        for row in range(self.paytable_table.rowCount()):
            symbol_item = self.paytable_table.item(row, 0)
            if not symbol_item:
                continue
            symbol_id = symbol_item.text()
            values = [
                self.paytable_table.item(row, col).text()
                if self.paytable_table.item(row, col) else "0"
                for col in range(1, 5)
            ]
            existing_values[symbol_id] = values

        self.paytable_table.setRowCount(0)
        for row in range(self.symbols_table.rowCount()):
            symbol_item = self.symbols_table.item(row, 0)
            if not symbol_item:
                continue
            symbol_id = symbol_item.text().strip()
            if not symbol_id:
                continue

            new_row = self.paytable_table.rowCount()
            self.paytable_table.insertRow(new_row)

            symbol_cell = QTableWidgetItem(symbol_id)
            symbol_cell.setFlags(symbol_cell.flags() & ~Qt.ItemIsEditable)
            self.paytable_table.setItem(new_row, 0, symbol_cell)

            default_values = existing_values.get(symbol_id, ["0", "5", "20", "100"])
            for index, value in enumerate(default_values):
                self.paytable_table.setItem(new_row, index + 1, QTableWidgetItem(str(value)))

    def get_paytable(self):
        paytable = {}
        for row in range(self.paytable_table.rowCount()):
            symbol_item = self.paytable_table.item(row, 0)
            if not symbol_item:
                continue
            symbol_id = symbol_item.text().strip()
            symbol_pays = {}
            for col, count in [(1, 2), (2, 3), (3, 4), (4, 5)]:
                item = self.paytable_table.item(row, col)
                val = self.parse_float(item.text() if item else "0")
                if val > 0:
                    symbol_pays[count] = val
            paytable[symbol_id] = symbol_pays
        return paytable

    # =====================================================
    # REELS TAB & RANDOM GENERATOR
    # =====================================================

    def create_reels_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        gen_box = QGroupBox("🎲 Random Reels Generator (Разная длина для каждого барабана)")
        gen_layout = QVBoxLayout(gen_box)

        spins_layout = QHBoxLayout()
        self.reel_gen_spins = []
        default_lengths = [55, 55, 60, 55, 55]

        for i in range(5):
            box = QVBoxLayout()
            box.addWidget(QLabel(f"Reel {i + 1}:"))
            spin = QSpinBox()
            spin.setRange(3, 5000)
            spin.setValue(default_lengths[i])
            self.reel_gen_spins.append(spin)
            box.addWidget(spin)
            spins_layout.addLayout(box)

        gen_layout.addLayout(spins_layout)

        gen_btn_layout = QHBoxLayout()
        generate_btn = QPushButton("🎲 Generate Random Strips for All Reels")
        generate_btn.setStyleSheet("QPushButton { font-weight: bold; background-color: #2b5b84; color: white; padding: 6px; }")
        generate_btn.clicked.connect(self.generate_random_reels)
        gen_btn_layout.addWidget(generate_btn)

        set_all_btn = QPushButton("Set Same Length to All...")
        set_all_btn.clicked.connect(self.action_set_all_reel_lengths)
        gen_btn_layout.addWidget(set_all_btn)

        gen_layout.addLayout(gen_btn_layout)
        layout.addWidget(gen_box)

        self.reel_combo = QComboBox()
        self.reel_combo.addItems(["Reel 1", "Reel 2", "Reel 3", "Reel 4", "Reel 5"])
        layout.addWidget(self.reel_combo)
        layout.addWidget(QLabel("Manual symbol editor (one symbol per line):"))

        self.reel_editors = []
        for _ in range(5):
            editor = QTextEdit()
            editor.setPlaceholderText("A\nK\nQ\nSCATTER\n...")
            editor.textChanged.connect(self.update_reel_distribution)
            editor.hide()
            self.reel_editors.append(editor)
            layout.addWidget(editor)

        self.reel_editors[0].show()
        self.reel_combo.currentIndexChanged.connect(self.change_reel_editor)

        self.reel_length_label = QLabel("Reel Length: 0")
        layout.addWidget(self.reel_length_label)

        self.reel_distribution_table = QTableWidget(0, 3)
        self.reel_distribution_table.setHorizontalHeaderLabels(["Symbol", "Count", "Reel %"])
        self.reel_distribution_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.reel_distribution_table)

        load_default_btn = QPushButton("Load Example Preset Reels")
        load_default_btn.clicked.connect(self.load_example_reels)
        layout.addWidget(load_default_btn)

        return widget

    def action_set_all_reel_lengths(self):
        val = self.reel_gen_spins[0].value()
        for spin in self.reel_gen_spins:
            spin.setValue(val)

    def generate_random_reels(self):
        regular_symbols = []
        for row in range(self.symbols_table.rowCount()):
            item = self.symbols_table.item(row, 0)
            if item and item.text().strip():
                regular_symbols.append(item.text().strip())

        if not regular_symbols:
            QMessageBox.warning(self, "No Symbols", "Добавьте хотя бы один символ во вкладке SYMBOLS перед генерацией.")
            return

        wild_cfg = self.get_wild_config()
        scatter_cfg = self.get_scatter_config()

        for reel_idx in range(5):
            target_len = self.reel_gen_spins[reel_idx].value()
            pool = list(regular_symbols)

            if wild_cfg.enabled and reel_idx in wild_cfg.allowed_reels:
                pool.append(wild_cfg.symbol_id)

            for sc in scatter_cfg.scatters:
                if sc.enabled and reel_idx in sc.allowed_reels:
                    pool.append(sc.symbol_id)

            generated = random.choices(pool, k=target_len)
            self.reel_editors[reel_idx].setPlainText("\n".join(generated))

        self.update_reel_distribution()
        QMessageBox.information(
            self,
            "Success",
            f"Барабаны успешно сгенерированы со следующими длинами:\n"
            f"Reel 1: {self.reel_gen_spins[0].value()}, "
            f"Reel 2: {self.reel_gen_spins[1].value()}, "
            f"Reel 3: {self.reel_gen_spins[2].value()}, "
            f"Reel 4: {self.reel_gen_spins[3].value()}, "
            f"Reel 5: {self.reel_gen_spins[4].value()}"
        )

    def change_reel_editor(self, index):
        for editor in self.reel_editors:
            editor.hide()
        self.reel_editors[index].show()
        self.update_reel_distribution()

    def load_example_reels(self):
        reels = [
            ["A", "K", "Q", "J", "10", "SCATTER", "K", "7", "Q", "A", "J", "K", "10", "A", "Q", "K"],
            ["K", "A", "Q", "10", "7", "SCATTER", "A", "K", "A", "Q", "J", "A", "10", "K", "Q", "A"],
            ["Q", "A", "K", "A", "J", "SCATTER", "10", "Q", "K", "A", "J", "A", "Q", "10", "K", "A"],
            ["A", "J", "K", "Q", "10", "SCATTER", "A", "K", "Q", "A", "J", "A", "K", "10", "Q", "A"],
            ["J", "A", "Q", "K", "10", "SCATTER", "7", "Q", "K", "J", "A", "A", "Q", "10", "K", "A"]
        ]
        for index in range(5):
            self.reel_editors[index].setPlainText("\n".join(reels[index]))
            if hasattr(self, "reel_gen_spins"):
                self.reel_gen_spins[index].setValue(len(reels[index]))
        self.update_reel_distribution()

    def update_reel_distribution(self):
        reel_index = self.reel_combo.currentIndex()
        if reel_index < 0 or reel_index >= len(self.reel_editors):
            return
        total, distribution = self.calculate_reel_distribution(reel_index)
        self.reel_length_label.setText(f"Reel Length: {total}")
        self.reel_distribution_table.setRowCount(0)

        for symbol, count, percentage in distribution:
            row = self.reel_distribution_table.rowCount()
            self.reel_distribution_table.insertRow(row)
            self.reel_distribution_table.setItem(row, 0, QTableWidgetItem(symbol))
            self.reel_distribution_table.setItem(row, 1, QTableWidgetItem(str(count)))
            self.reel_distribution_table.setItem(row, 2, QTableWidgetItem(f"{percentage:.4f} %"))

    def calculate_reel_distribution(self, reel_index: int):
        editor = self.reel_editors[reel_index]
        symbols = [s.strip() for s in editor.toPlainText().splitlines() if s.strip()]
        total = len(symbols)
        counts = {}
        for symbol in symbols:
            counts[symbol] = counts.get(symbol, 0) + 1

        result = [
            (sym, counts[sym], (counts[sym] / total * 100 if total > 0 else 0))
            for sym in sorted(counts.keys())
        ]
        return total, result

    def get_reels(self):
        reels = []
        for index, editor in enumerate(self.reel_editors):
            symbols = [s.strip() for s in editor.toPlainText().splitlines() if s.strip()]
            if not symbols:
                raise ValueError(f"Reel {index + 1} is empty.")
            reels.append(Reel(symbols))
        return reels

    # =====================================================
    # PAYLINES TAB
    # =====================================================

    def create_paylines_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info = QLabel(
            "Select paylines used by the game.\n"
            "Each digit is the row index for its reel."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.payline_table = QTableWidget(0, 3)
        self.payline_table.setHorizontalHeaderLabels(["Use", "#", "Pattern"])
        self.payline_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.payline_table)

        load_btn = QPushButton("Reload Paylines")
        load_btn.clicked.connect(self.reload_paylines)
        layout.addWidget(load_btn)

        return widget

    def reload_paylines(self):
        rows = self.get_rows()
        available_lines = lines_53 if rows == 3 else lines_54
        active_count = min(self.lines_spin.value(), len(available_lines))

        self.payline_table.setRowCount(0)
        for index, pattern in enumerate(available_lines):
            row = self.payline_table.rowCount()
            self.payline_table.insertRow(row)

            checkbox = QCheckBox()
            checkbox.setChecked(index < active_count)
            checkbox.stateChanged.connect(self.update_bet_information)
            self.payline_table.setCellWidget(row, 0, checkbox)

            number_item = QTableWidgetItem(str(index + 1))
            number_item.setFlags(number_item.flags() & ~Qt.ItemIsEditable)
            self.payline_table.setItem(row, 1, number_item)

            pattern_item = QTableWidgetItem(pattern)
            pattern_item.setFlags(pattern_item.flags() & ~Qt.ItemIsEditable)
            self.payline_table.setItem(row, 2, pattern_item)

        self.update_bet_information()

    def get_selected_paylines(self):
        selected = []
        for row in range(self.payline_table.rowCount()):
            checkbox = self.payline_table.cellWidget(row, 0)
            pattern_item = self.payline_table.item(row, 2)
            if checkbox and checkbox.isChecked() and pattern_item:
                selected.append(pattern_item.text())
        return selected

    def get_active_payline_count(self):
        if not hasattr(self, "payline_table"):
            return self.lines_spin.value()
        selected = self.get_selected_paylines()
        return len(selected) if selected else self.lines_spin.value()

    def update_bet_information(self):
        total_bet = self.total_bet_spin.value()
        active_lines = max(1, self.get_active_payline_count())
        bet_per_line = total_bet / active_lines
        self.calculated_bet_per_line_label.setText(f"{bet_per_line:.6f}")

    # =====================================================
    # GRID & SPINS
    # =====================================================

    def get_rows(self):
        return 3 if self.field_combo.currentText() == "5x3" else 4

    def update_grid_preview(self):
        if not hasattr(self, "grid_layout"):
            return

        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        rows = self.get_rows()
        self.grid_labels = []

        for row in range(rows):
            row_labels = []
            for reel in range(5):
                label = QLabel("-")
                label.setAlignment(Qt.AlignCenter)
                label.setMinimumSize(80, 80)
                label.setStyleSheet(
                    """
                    QLabel {
                        border: 2px solid #555;
                        font-size: 18px;
                        font-weight: bold;
                        background: #20242b;
                        color: white;
                    }
                    """
                )
                self.grid_layout.addWidget(label, row, reel)
                row_labels.append(label)
            self.grid_labels.append(row_labels)

    def display_grid(self, grid):
        rows = self.get_rows()
        for row in range(rows):
            for reel in range(5):
                self.grid_labels[row][reel].setText(grid[reel][row])

    def run_single_spin(self):
        try:
            reels = self.get_reels()
            paytable = self.get_paytable()
            paylines = self.get_selected_paylines()

            if not paylines:
                QMessageBox.warning(self, "No Paylines", "Select at least one payline.")
                return

            wild_config = self.get_wild_config()
            scatter_config = self.get_scatter_config()
            rng_algo, seed = self.get_rng_config()

            total_bet = self.total_bet_spin.value()
            bet_per_line = total_bet / len(paylines)
            payout_base = self.payout_base_combo.currentData()

            simulator = SlotSimulator(
                reels=reels,
                paylines=paylines,
                paytable=paytable,
                total_bet=total_bet,
                bet_per_line=bet_per_line,
                payout_base=payout_base,
                rng_algorithm=rng_algo,
                seed=seed,
                wild_config=wild_config,
                scatter_config=scatter_config
            )

            rows = self.get_rows()
            grid = simulator.spin(rows=rows)

            regular_symbols = set(paytable.keys())
            if wild_config.enabled:
                regular_symbols.discard(wild_config.symbol_id)

            scatter_symbols = {sc.symbol_id for sc in scatter_config.scatters if sc.enabled}
            regular_symbols.difference_update(scatter_symbols)

            if wild_config.enabled:
                processing = simulator.wild_processor.process_grid(
                    grid=grid,
                    regular_symbols=regular_symbols,
                    scatter_symbols=scatter_symbols
                )
                grid = processing.grid

            evaluation = simulator.evaluator.evaluate_spin(
                grid=grid,
                paylines=paylines,
                payout_base_value=simulator.get_payout_base_value(),
                payout_base_type=simulator.payout_base,
                scatter_config=scatter_config,
                total_bet=total_bet
            )

            self.display_grid(grid)

            details = []
            for win in evaluation.line_wins:
                details.append(
                    f"Line {win.line_index + 1} [{win.line_pattern}] | "
                    f"{win.symbol} x{win.match_count} | Multiplier ×{win.multiplier:g} | "
                    f"Win: {win.win:.4f}"
                )

            for sc_win in evaluation.scatter_wins:
                details.append(
                    f"★ SCATTER [{sc_win.symbol}] x{sc_win.count} on screen | "
                    f"Multiplier ×{sc_win.multiplier:g} Total Bet | Win: {sc_win.win:.4f}"
                )

            if not details:
                details.append("No winning combinations.")

            QMessageBox.information(
                self,
                "Single Spin Result",
                f"Total Win: {evaluation.total_win:.4f}\n\n" + "\n".join(details)
            )

        except Exception as error:
            QMessageBox.critical(self, "Spin Error", str(error))

    # =====================================================
    # SIMULATION
    # =====================================================

    def run_simulation(self):
        try:
            reels = self.get_reels()
            paytable = self.get_paytable()
        except Exception as error:
            QMessageBox.critical(self, "Configuration Error", str(error))
            return

        rows = self.get_rows()
        paylines = self.get_selected_paylines()
        if not paylines:
            QMessageBox.warning(self, "No Paylines", "Select at least one payline.")
            return

        wild_config = self.get_wild_config()
        scatter_config = self.get_scatter_config()

        validator = ModelValidator()
        validation_messages = validator.validate(
            reels=reels,
            paytable=paytable,
            paylines=paylines,
            rows=rows,
            wild_config=wild_config,
            scatter_config=scatter_config
        )
        errors = [m for m in validation_messages if m.severity == "ERROR"]

        if errors:
            error_text = "\n".join(f"[{e.category}] {e.message}" for e in errors)
            QMessageBox.critical(self, "Math Model Validation Failed", error_text)
            return

        total_bet = self.total_bet_spin.value()
        bet_per_line = total_bet / len(paylines) if len(paylines) > 0 else 0.0
        payout_base = self.payout_base_combo.currentData()
        rng_algo, seed = self.get_rng_config()

        simulation_params = {
            "reels": reels,
            "paylines": paylines,
            "paytable": paytable,
            "total_bet": total_bet,
            "bet_per_line": bet_per_line,
            "payout_base": payout_base,
            "wild_config": wild_config,
            "scatter_config": scatter_config,
            "rng_algorithm": rng_algo,
            "seed": seed,
            "spins": self.simulation_spins.value(),
            "rows": rows
        }

        self.set_ui_running_state(True)
        self.progress_bar.setValue(0)
        self.progress_info_label.setText(f"Starting simulation ({rng_algo})...")

        self.simulation_worker = AsyncSimulationWorker(simulation_params)
        self.simulation_worker.progress_signal.connect(self.on_simulation_progress)
        self.simulation_worker.finished_signal.connect(self.on_simulation_finished)
        self.simulation_worker.error_signal.connect(self.on_simulation_error)
        self.simulation_worker.start()

    def cancel_simulation(self):
        if self.simulation_worker and self.simulation_worker.isRunning():
            self.progress_info_label.setText("Cancelling simulation...")
            self.simulation_worker.cancel()
            self.set_ui_running_state(False)

    def set_ui_running_state(self, is_running: bool):
        self.run_button.setEnabled(not is_running)
        self.single_spin_button.setEnabled(not is_running)
        self.cancel_button.setEnabled(is_running)

    def on_simulation_progress(self, percent: int, done: int, total: int):
        self.progress_bar.setValue(percent)
        self.progress_info_label.setText(f"Simulating: {done:,} / {total:,} spins ({percent}%)")

    def on_simulation_finished(self, result: SimulationResult):
        self.last_simulation_result = result
        self.set_ui_running_state(False)
        self.progress_bar.setValue(100)
        self.progress_info_label.setText(f"Completed {result.spins:,} spins successfully.")

        self.spins_label.setText(f"Spins: {result.spins:,}")
        self.total_bet_label.setText(f"Total Bet: {result.total_bet:,.2f}")
        self.total_win_label.setText(f"Total Win: {result.total_win:,.2f}")
        self.rtp_label.setText(f"RTP: {result.rtp:.6f} %")
        self.hit_rate_label.setText(f"Hit Rate: {result.hit_rate:.6f} %")
        self.hit_frequency_label.setText(f"Hit Frequency: 1 : {result.hit_frequency:.4f}")
        self.max_win_label.setText(f"Max Win: {result.max_win:,.2f}")
        self.max_win_x_label.setText(f"Max Win X: {result.max_win_x:.6f} x")

        self.display_statistics(result)

    def on_simulation_error(self, err_msg: str):
        self.set_ui_running_state(False)
        self.progress_info_label.setText("Error during simulation.")
        QMessageBox.critical(self, "Simulation Error", err_msg)

    # =====================================================
    # STATISTICS DISPLAY
    # =====================================================

    def display_statistics(self, result):
        self.display_combination_statistics(result)
        self.display_scatter_statistics(result)
        self.display_symbol_statistics(result)
        self.display_win_distribution(result)
        self.display_wild_statistics(result)

    def display_combination_statistics(self, result):
        table = self.combination_table
        table.setRowCount(0)
        stats = result.statistics.combinations

        sorted_items = sorted(stats.items(), key=lambda item: (item[0][0], item[0][1]))
        for (symbol, count), cstat in sorted_items:
            row = table.rowCount()
            table.insertRow(row)
            hit_pct = (cstat.hits / result.spins * 100.0) if result.spins > 0 else 0.0
            rtp_contrib = (cstat.total_win / result.total_bet * 100.0) if result.total_bet > 0 else 0.0

            values = [
                symbol,
                str(count),
                f"{cstat.hits:,}",
                f"{hit_pct:.6f} %",
                f"{cstat.total_win:,.2f}",
                f"{rtp_contrib:.6f} %"
            ]
            for col, val in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(val))

    def display_scatter_statistics(self, result):
        table = self.scatter_statistics_table
        table.setRowCount(0)
        scatters_stat = result.statistics.scatters

        for sc_symbol, sc_stat in sorted(scatters_stat.items()):
            for count, hits in sorted(sc_stat.hits_by_count.items()):
                if hits == 0:
                    continue
                row = table.rowCount()
                table.insertRow(row)

                hit_pct = (hits / result.spins * 100.0) if result.spins > 0 else 0.0
                sc_pays = {}
                for sc in self.get_scatter_config().scatters:
                    if sc.symbol_id == sc_symbol:
                        sc_pays = sc.pays
                        break
                multiplier = sc_pays.get(count, 0.0)
                scatter_win = hits * (self.total_bet_spin.value() * multiplier)
                rtp_contrib = (scatter_win / result.total_bet * 100.0) if result.total_bet > 0 else 0.0

                values = [
                    sc_symbol,
                    f"x{count}",
                    f"{hits:,}",
                    f"{hit_pct:.6f} %",
                    f"{scatter_win:,.2f}",
                    f"{rtp_contrib:.6f} %"
                ]
                for col, val in enumerate(values):
                    table.setItem(row, col, QTableWidgetItem(val))

    def display_symbol_statistics(self, result):
        # 1. Первая таблица: общая статистика выигрышей и частоты
        table1 = self.symbol_statistics_table
        table1.setRowCount(0)
        stats = result.statistics
        total_gen = sum(stats.symbol_generated.values())

        for symbol in sorted(stats.symbol_generated.keys()):
            gen = stats.symbol_generated[symbol]
            freq = (gen / total_gen * 100.0) if total_gen > 0 else 0.0
            s_stat = stats.symbols.get(symbol)
            win = s_stat.total_win if s_stat else 0.0
            rtp = (win / result.total_bet * 100.0) if result.total_bet > 0 else 0.0

            row = table1.rowCount()
            table1.insertRow(row)
            values = [symbol, f"{gen:,}", f"{freq:.4f} %", f"{win:,.2f}", f"{rtp:.6f} %"]
            for col, val in enumerate(values):
                table1.setItem(row, col, QTableWidgetItem(val))

        # 2. Вторая таблица: веса и распределение символов по всем 5 барабанам
        table2 = self.symbol_reels_table
        table2.setRowCount(0)
        reels = self.get_reels()

        for symbol in sorted(stats.symbol_generated.keys()):
            row = table2.rowCount()
            table2.insertRow(row)
            table2.setItem(row, 0, QTableWidgetItem(symbol))

            for r_idx in range(5):
                r_symbols = reels[r_idx].symbols if r_idx < len(reels) else []
                cnt = r_symbols.count(symbol)
                pct = (cnt / len(r_symbols) * 100.0) if len(r_symbols) > 0 else 0.0
                cell_text = f"{cnt} ({pct:.2f} %)" if cnt > 0 else "-"
                table2.setItem(row, r_idx + 1, QTableWidgetItem(cell_text))

        # Итоговая строка длины барабанов
        len_row = table2.rowCount()
        table2.insertRow(len_row)
        table2.setItem(len_row, 0, QTableWidgetItem("Total Length"))
        for r_idx in range(5):
            r_len = len(reels[r_idx].symbols) if r_idx < len(reels) else 0
            table2.setItem(len_row, r_idx + 1, QTableWidgetItem(f"{r_len} symbols"))

    def display_win_distribution(self, result):
        table = self.win_distribution_table
        table.setRowCount(0)
        order = ["0x", "0-1x", "1-2x", "2-5x", "5-10x", "10-20x", "20-50x", "50-100x", "100-500x", "500-1000x", "1000x+"]
        dist = result.statistics.win_distribution

        for bucket in order:
            cnt = dist.get(bucket, 0)
            pct = (cnt / result.spins * 100.0) if result.spins > 0 else 0.0
            row = table.rowCount()
            table.insertRow(row)
            for col, val in enumerate([bucket, f"{cnt:,}", f"{pct:.4f} %"]):
                table.setItem(row, col, QTableWidgetItem(val))

    def display_wild_statistics(self, result):
        table = self.wild_statistics_table
        table.setRowCount(0)
        wild = result.statistics.wild
        wild_freq = (result.spins / wild.spins_with_wild) if wild.spins_with_wild > 0 else 0.0
        wild_rtp = (wild.win_amount_with_wild / result.total_bet * 100.0) if result.total_bet > 0 else 0.0

        metrics = [
            ("Wild landed", f"{wild.landed:,}"),
            ("Spins with Wild", f"{wild.spins_with_wild:,}"),
            ("Wild Spin Frequency", f"1 : {wild_freq:.4f}" if wild_freq > 0 else "-"),
            ("Expanded Cells", f"{wild.expanded_cells:,}"),
            ("Boom Generated Cells", f"{wild.boom_cells:,}"),
            ("Winning Lines Using Wild", f"{wild.wins_with_wild:,}"),
            ("Win Amount Using Wild", f"{wild.win_amount_with_wild:,.2f}"),
            ("Wild RTP Contribution", f"{wild_rtp:.6f} %")
        ]

        for metric, value in metrics:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(metric))
            table.setItem(row, 1, QTableWidgetItem(value))

    def parse_float(self, value: str, default: float = 0.0):
        if value is None:
            return default
        try:
            return float(str(value).strip().replace(",", "."))
        except ValueError:
            return default