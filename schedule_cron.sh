#!/bin/bash
# ============================================================
#  Lancement automatique du bot tous les matins
#  Ce script est conçu pour être appelé par cron (Linux/Mac)
#  ou par le Planificateur de tâches Windows
# ============================================================

# Répertoire du projet (adapter si besoin)
PROJET_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Activer l'environnement virtuel s'il existe
if [ -d "$PROJET_DIR/.venv" ]; then
    source "$PROJET_DIR/.venv/bin/activate"
fi

# Lancer le bot
cd "$PROJET_DIR" && python main.py

# ============================================================
#  INSTALLATION (Linux/Mac)
# ============================================================
#
#  1. Rends ce script exécutable :
#       chmod +x schedule_cron.sh
#
#  2. Ouvre l'éditeur cron :
#       crontab -e
#
#  3. Ajoute cette ligne (lance le bot à 7h30 chaque matin) :
#       30 7 * * * /chemin/vers/Job-search/schedule_cron.sh
#
#  Format cron : minute heure jour mois jour_semaine commande
#  Exemples :
#    30 7 * * 1-5   = 7h30 du lundi au vendredi seulement
#    0 8 * * *      = 8h00 tous les jours
#
#  4. Vérifie que cron tourne :
#       sudo service cron status    (Debian/Ubuntu)
#       sudo systemctl status crond (CentOS/Fedora)
#
# ============================================================
#  INSTALLATION (Windows)
# ============================================================
#
#  Option 1 : Planificateur de tâches Windows (interface graphique)
#    Chercher "Planificateur de tâches" dans le menu démarrer
#    → Créer une tâche de base
#    → Déclencheur : quotidien à 7h30
#    → Action : démarrer un programme
#    → Programme : python
#    → Arguments : main.py
#    → Démarrer dans : C:\chemin\vers\Job-search
#
#  Option 2 : PowerShell (une seule fois en admin)
#    $action = New-ScheduledTaskAction -Execute 'python' -Argument 'main.py' -WorkingDirectory 'C:\chemin\vers\Job-search'
#    $trigger = New-ScheduledTaskTrigger -Daily -At '07:30'
#    Register-ScheduledTask -TaskName 'JobBot' -Action $action -Trigger $trigger
#
# ============================================================
#  TEST MANUEL
# ============================================================
#  Pour tester le bot manuellement :
#    python main.py
#
#  Pour voir les logs :
#    tail -f logs/bot.log
#
#  Pour voir la base de données :
#    sqlite3 data/jobs.db "SELECT title, score, found_at FROM offers ORDER BY score DESC LIMIT 10;"
