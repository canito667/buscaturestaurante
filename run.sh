#!/usr/bin/env bash
# Arranca la app BuscaTuRestaurante en modo "datos de internet".
# Uso:  ./run.sh
set -e
cd "$(dirname "$0")"

# Si no existe el entorno virtual, lo crea e instala dependencias
if [ ! -d ".venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -r requirements.txt
fi

echo "Abriendo la app en http://localhost:8501"
.venv/bin/streamlit run app.py --server.port 8501
