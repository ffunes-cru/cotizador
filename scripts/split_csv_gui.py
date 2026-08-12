#!/usr/bin/env python3
"""
Interfaz gráfica Qt para la división de archivos CSV pesados de Sembradoras.
Soporta PyQt6, PySide6 y PyQt5 con detección automática de bindings.
"""

import sys
import os
import csv
import trace

# Importación dinámica de bindings Qt (PyQt6 / PySide6 / PyQt5)
try:
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                 QSpinBox, QTextEdit, QFileDialog, QMessageBox,
                                 QGroupBox, QProgressBar)
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QFont, QIcon
except ImportError:
    try:
        from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                     QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                     QSpinBox, QTextEdit, QFileDialog, QMessageBox,
                                     QGroupBox, QProgressBar)
        from PySide6.QtCore import Qt, QThread, Signal as pyqtSignal
        from PySide6.QtGui import QFont, QIcon
    except ImportError:
        from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                     QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                     QSpinBox, QTextEdit, QFileDialog, QMessageBox,
                                     QGroupBox, QProgressBar)
        from PyQt5.QtCore import Qt, QThread, pyqtSignal
        from PyQt5.QtGui import QFont, QIcon


class SplitWorker(QThread):
    """Hilo de trabajo secundario para no congelar la GUI durante el procesado."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, input_file, max_configs, output_dir):
        super().__init__()
        self.input_file = input_file
        self.max_configs = max_configs
        self.output_dir = output_dir

    def run(self):
        try:
            if not os.path.exists(self.input_file):
                self.finished_signal.emit(False, f"El archivo '{self.input_file}' no existe.")
                return

            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir)

            self.log_signal.emit(f"📖 Leyendo '{self.input_file}'...")
            with open(self.input_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                rows = list(reader)

            if not rows:
                self.finished_signal.emit(False, "El archivo CSV está vacío.")
                return

            # Agrupar filas manteniendo la integridad de cada ID_Configuracion
            grouped = {}
            order = []
            for r in rows:
                cid = r.get('ID_Configuracion', '').strip()
                if not cid:
                    continue
                if cid not in grouped:
                    grouped[cid] = []
                    order.append(cid)
                grouped[cid].append(r)

            total_configs = len(order)
            self.log_signal.emit(f"✅ Total de configuraciones únicas detectadas: {total_configs}")

            file_idx = 1
            current_chunk_configs = []

            for cid in order:
                current_chunk_configs.append(cid)
                if len(current_chunk_configs) >= self.max_configs:
                    self._write_chunk(file_idx, fieldnames, current_chunk_configs, grouped)
                    file_idx += 1
                    current_chunk_configs = []

            if current_chunk_configs:
                self._write_chunk(file_idx, fieldnames, current_chunk_configs, grouped)

            total_created = file_idx if current_chunk_configs else file_idx - 1
            self.finished_signal.emit(
                True, f"🎉 Proceso completado exitosamente.\nSe generaron {total_created} archivos en la carpeta '{self.output_dir}'."
            )

        except Exception as e:
            self.finished_signal.emit(False, f"Error durante el procesamiento: {str(e)}")

    def _write_chunk(self, file_idx, fieldnames, config_ids, grouped):
        out_filename = os.path.join(self.output_dir, f"parte_{file_idx:02d}.csv")
        with open(out_filename, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            total_rows = 0
            for cid in config_ids:
                for row in grouped[cid]:
                    writer.writerow(row)
                    total_rows += 1
        self.log_signal.emit(f"  📄 Generado '{os.path.basename(out_filename)}': {len(config_ids)} configuraciones ({total_rows} filas)")


class CSVSplitterGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Divisor de CSV - Cotizador de Sembradoras")
        self.resize(650, 520)
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Encabezado
        header_label = QLabel("Divisor de CSV para Cotizador de Sembradoras")
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header_label.setFont(header_font)
        main_layout.addWidget(header_label)

        sub_label = QLabel("Divida archivos CSV de configuraciones pesadas en partes listas para importar en Odoo.")
        main_layout.addWidget(sub_label)

        # Grupo de Configuración
        group_box = QGroupBox("Parámetros de Selección")
        group_layout = QVBoxLayout(group_box)
        group_layout.setSpacing(12)

        # Archivo Entrada
        file_layout = QHBoxLayout()
        file_label = QLabel("Archivo CSV:")
        file_label.setFixedWidth(120)
        self.txt_file = QLineEdit()
        self.txt_file.setPlaceholderText("Seleccione el archivo .csv gigante...")
        btn_browse_file = QPushButton("Buscar...")
        btn_browse_file.clicked.connect(self.browse_file)
        file_layout.addWidget(file_label)
        file_layout.addWidget(self.txt_file)
        file_layout.addWidget(btn_browse_file)
        group_layout.addLayout(file_layout)

        # Carpeta Salida
        out_layout = QHBoxLayout()
        out_label = QLabel("Carpeta Destino:")
        out_label.setFixedWidth(120)
        self.txt_output = QLineEdit()
        self.txt_output.setPlaceholderText("Directorio donde se guardarán las partes...")
        btn_browse_out = QPushButton("Seleccionar...")
        btn_browse_out.clicked.connect(self.browse_output)
        out_layout.addWidget(out_label)
        out_layout.addWidget(self.txt_output)
        out_layout.addWidget(btn_browse_out)
        group_layout.addLayout(out_layout)

        # Límite por parte
        chunk_layout = QHBoxLayout()
        chunk_label = QLabel("Configs por parte:")
        chunk_label.setFixedWidth(120)
        self.num_max_configs = QSpinBox()
        self.num_max_configs.setRange(10, 5000)
        self.num_max_configs.setValue(150)
        self.num_max_configs.setFixedWidth(100)
        help_chunk = QLabel("(Recomendado: 150 a 200 configuraciones por archivo)")
        chunk_layout.addWidget(chunk_label)
        chunk_layout.addWidget(self.num_max_configs)
        chunk_layout.addWidget(help_chunk)
        chunk_layout.addStretch()
        group_layout.addLayout(chunk_layout)

        main_layout.addWidget(group_box)

        # Botón Acción Principal Nativo
        self.btn_run = QPushButton("Dividir Archivo CSV")
        btn_font = QFont()
        btn_font.setBold(True)
        self.btn_run.setFont(btn_font)
        self.btn_run.setFixedHeight(36)
        self.btn_run.clicked.connect(self.run_split)
        main_layout.addWidget(self.btn_run)

        # Consola / Log de Salida
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        main_layout.addWidget(self.txt_log)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo CSV", "", "Archivos CSV (*.csv)")
        if path:
            self.txt_file.setText(path)
            if not self.txt_output.text():
                default_out = os.path.join(os.path.dirname(path), "csv_partes")
                self.txt_output.setText(default_out)

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta de Destino")
        if path:
            self.txt_output.setText(path)

    def log(self, text):
        self.txt_log.append(text)

    def run_split(self):
        input_file = self.txt_file.text().strip()
        output_dir = self.txt_output.text().strip()
        max_configs = self.num_max_configs.value()

        if not input_file:
            QMessageBox.warning(self, "Atención", "Por favor, seleccione un archivo CSV de entrada.")
            return

        if not output_dir:
            output_dir = os.path.join(os.path.dirname(input_file), "csv_partes")
            self.txt_output.setText(output_dir)

        self.txt_log.clear()
        self.btn_run.setEnabled(False)
        self.log("Iniciando división del archivo...")

        # Iniciar hilo de trabajo secundario
        self.worker = SplitWorker(input_file, max_configs, output_dir)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, success, message):
        self.btn_run.setEnabled(True)
        if success:
            self.log(f"\n{message}")
            QMessageBox.information(self, "Éxito", message)
        else:
            self.log(f"\n{message}")
            QMessageBox.critical(self, "Error", message)


def main():
    app = QApplication(sys.argv)
    window = CSVSplitterGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
