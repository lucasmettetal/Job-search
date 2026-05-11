# Créer un exécutable .exe avec PyInstaller

> ⚠️ Note : Créer un .exe d'une app Streamlit est complexe et fragile.
> **La méthode recommandée reste le double-clic sur `launch_app.bat`.**
> Ce guide est pour les cas où tu veux distribuer le bot sans Python installé.

## Méthode recommandée : launch_app.bat (plus simple)

Le fichier `launch_app.bat` fait tout automatiquement :
- Vérifie Python
- Installe les dépendances
- Lance Streamlit

**C'est la meilleure option pour un usage perso.**

---

## Méthode alternative : PyInstaller + wrapper

### Prérequis

```bash
pip install pyinstaller
```

### Limitation importante

Streamlit n'est pas conçu pour être packagé avec PyInstaller.
La solution est de créer un **script lanceur** qui démarre Streamlit
en sous-processus depuis l'exécutable.

### Étape 1 : Créer run_bot.py (lanceur simple)

Ce script est ce que PyInstaller va compiler.
Il lance `streamlit run app.py` depuis le bon répertoire.

```python
# run_bot.py — à créer à la racine du projet
import subprocess
import sys
import os
from pathlib import Path

def main():
    # Répertoire du .exe (ou du script)
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).parent

    os.chdir(base_dir)

    streamlit = base_dir / "streamlit.exe"  # Windows
    if not streamlit.exists():
        streamlit = "streamlit"

    subprocess.run([
        str(streamlit), "run",
        str(base_dir / "app.py"),
        "--server.port", "8501",
        "--server.headless", "false",
    ])

if __name__ == "__main__":
    main()
```

### Étape 2 : Compiler avec PyInstaller

```bash
pyinstaller \
  --onefile \
  --name "JobBot" \
  --add-data "app.py;." \
  --add-data "config.yaml;." \
  --add-data "bot;bot" \
  --add-data ".streamlit;.streamlit" \
  --hidden-import streamlit \
  --hidden-import yaml \
  --hidden-import pandas \
  --hidden-import bs4 \
  run_bot.py
```

Sur Windows, remplace `:` par `;` dans `--add-data`.
Sur Linux/Mac, utilise `:`.

### Étape 3 : Distribuer

Le dossier `dist/` contiendra `JobBot.exe` (Windows) ou `JobBot` (Linux).

Inclure dans l'archive de distribution :
```
JobBot.exe          ← l'exécutable
config.yaml         ← configuration
.env.example        ← template des secrets
data/               ← dossier vide
logs/               ← dossier vide
```

L'utilisateur devra :
1. Copier `.env.example` en `.env`
2. Remplir ses clés API
3. Double-cliquer sur `JobBot.exe`

---

## Méthode la plus propre : script d'installation

Au lieu d'un .exe, crée un script d'installation :

```batch
:: install.bat
@echo off
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
echo Installation terminee !
echo Lance launch_app.bat pour demarrer.
pause
```

L'utilisateur installe une fois, puis utilise `launch_app.bat` au quotidien.

---

## Résumé des options

| Méthode | Simplicité | Fiabilité | Mise à jour |
|---|---|---|---|
| `launch_app.bat` | ⭐⭐⭐ | ⭐⭐⭐ | Facile |
| PyInstaller .exe | ⭐ | ⭐ | Difficile |
| Script install + bat | ⭐⭐ | ⭐⭐⭐ | Facile |

**Recommandation : reste sur `launch_app.bat`.** C'est simple, fiable,
et tu peux modifier le code sans recompiler.
