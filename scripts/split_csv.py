#!/usr/bin/env python3
"""
Script de utilidad para dividir archivos CSV pesados de configuraciones de sembradora
en partes más pequeñas, garantizando que ninguna configuración (BASE + OPCIONALES)
quede cortada por la mitad.

Uso:
    python3 split_csv.py <archivo_gigante.csv> [configuraciones_por_archivo]

Ejemplo:
    python3 split_csv.py matriz_5000.csv 150
"""

import csv
import sys
import os

def split_sembradora_csv(input_filepath, max_configs_per_file=150, output_dir="csv_partes"):
    if not os.path.exists(input_filepath):
        print(f"Error: El archivo '{input_filepath}' no existe.")
        sys.exit(1)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Leyendo '{input_filepath}'...")
    with open(input_filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not rows:
        print("El archivo CSV está vacío.")
        sys.exit(1)

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
    print(f"Total de configuraciones únicas detectadas: {total_configs}")

    file_idx = 1
    current_chunk_configs = []

    for cid in order:
        current_chunk_configs.append(cid)
        if len(current_chunk_configs) >= max_configs_per_file:
            _write_chunk(output_dir, file_idx, fieldnames, current_chunk_configs, grouped)
            file_idx += 1
            current_chunk_configs = []

    if current_chunk_configs:
        _write_chunk(output_dir, file_idx, fieldnames, current_chunk_configs, grouped)

    print(f"\n✅ Proceso completado. Se generaron {file_idx if current_chunk_configs else file_idx-1} archivos en la carpeta '{output_dir}/'.")

def _write_chunk(output_dir, file_idx, fieldnames, config_ids, grouped):
    out_filename = os.path.join(output_dir, f"parte_{file_idx:02d}.csv")
    with open(out_filename, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        total_rows = 0
        for cid in config_ids:
            for row in grouped[cid]:
                writer.writerow(row)
                total_rows += 1
    print(f"  📄 Creado '{out_filename}': {len(config_ids)} configuraciones ({total_rows} filas)")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python3 split_csv.py <archivo.csv> [configs_por_parte]")
        sys.exit(1)
    
    csv_file_path = sys.argv[1]
    max_configs = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    split_sembradora_csv(csv_file_path, max_configs_per_file=max_configs)
