#!/usr/bin/env bash
# ============================================================
#  JobBot — Lancement de l'interface web (Linux / Mac)
#  Usage : ./launch_app.sh
#  Ou    : bash launch_app.sh
# ============================================================

set -e  # Arrêter en cas d'erreur

# Se placer dans le dossier du script (même si lancé depuis ailleurs)
cd "$(dirname "$0")"

echo ""
echo "============================================="
echo "  JobBot - Lancement de l'interface locale"
echo "============================================="
echo ""

# ---- Vérification de Python ----
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "[ERREUR] Python n'est pas installé."
    echo "Installe-le avec : sudo apt install python3  (Debian/Ubuntu)"
    echo "                ou : brew install python       (Mac)"
    exit 1
fi

# Choisir python3 si disponible, sinon python
PYTHON=$(command -v python3 || command -v python)
echo "  Python : $PYTHON"

# ---- Environnement virtuel ----
if [ -d ".venv" ]; then
    echo "  Activation de l'environnement virtuel..."
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
    PYTHON=python
elif [ -d "venv" ]; then
    echo "  Activation de l'environnement virtuel..."
    # shellcheck disable=SC1091
    source "venv/bin/activate"
    PYTHON=python
else
    echo "  Aucun .venv trouvé — utilisation du Python système"
fi

# ---- Installation des dépendances ----
echo "  Vérification des dépendances..."
"$PYTHON" -m pip install -r requirements.txt --quiet

# ---- Configuration Streamlit ----
mkdir -p .streamlit
cat > .streamlit/config.toml << 'EOF'
[server]
fileWatcherType = "none"
headless = false

[browser]
gatherUsageStats = false
EOF

# ---- Création des dossiers nécessaires ----
mkdir -p data logs

# ---- Lancement ----
echo ""
echo "  Ouverture dans le navigateur : http://localhost:8501"
echo "  Pour arrêter : Ctrl+C"
echo ""

"$PYTHON" -m streamlit run app.py \
    --server.port 8501 \
    --server.headless false
