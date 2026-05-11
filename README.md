# JobBot — Bot de veille emploi

Bot de recherche d'emploi automatisé pour Lucas Mettetal.
Cible : postes junior en sysadmin, réseau, support IT et cybersécurité en Occitanie.

## Architecture

```
Job-search/
├── config.yaml              ← TON fichier de config (mots-clés, villes, email...)
├── .env                     ← Tes secrets (jamais sur Git !)
├── main.py                  ← Lance le bot : python main.py
├── requirements.txt         ← Dépendances Python
├── schedule_cron.sh         ← Script pour lancer le bot automatiquement
├── ROADMAP.md               ← Plan des versions futures
│
├── bot/
│   ├── models.py            ← Structure d'une offre (JobOffer)
│   ├── database.py          ← SQLite : sauvegarde, anti-doublons
│   ├── scoring.py           ← Calcul du score de pertinence
│   ├── mailer.py            ← Envoi de l'email quotidien
│   ├── report.py            ← Génération HTML + texte du rapport
│   └── sources/
│       ├── base.py          ← Classe abstraite (modèle pour les sources)
│       └── france_travail.py ← API officielle France Travail
│
├── data/
│   └── jobs.db              ← Base SQLite (créée automatiquement)
└── logs/
    └── bot.log              ← Logs du bot
```

## Installation

### 1. Cloner et installer les dépendances

```bash
git clone <ton-repo>
cd Job-search
pip install -r requirements.txt
```

### 2. Configurer tes secrets

```bash
cp .env.example .env
# Édite .env avec tes identifiants
```

Contenu du `.env` :
```
FRANCE_TRAVAIL_CLIENT_ID=xxxxx
FRANCE_TRAVAIL_CLIENT_SECRET=xxxxx
EMAIL_SENDER=ton.email@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

### 3. Obtenir les identifiants France Travail (gratuit)

1. Va sur [francetravail.io/inscription](https://francetravail.io/inscription)
2. Crée un compte développeur
3. Crée une nouvelle application
4. Active l'API **"Offres d'emploi v2"**
5. Copie ton **Client ID** et **Client Secret** dans `.env`

### 4. Configurer Gmail

1. Active la validation en 2 étapes sur ton compte Google
2. Va dans : **Mon compte → Sécurité → Connexion → Mots de passe des applications**
3. Crée un mot de passe pour "Autre (nom personnalisé)" → `JobBot`
4. Copie ce mot de passe (16 caractères) dans `.env` → `EMAIL_APP_PASSWORD`

### 5. Personnaliser la configuration

Édite `config.yaml` pour adapter :
- Les mots-clés recherchés
- Les villes et le rayon
- Ton email de destination
- Les types de contrats

### 6. Lancer le bot

```bash
# Test immédiat
python main.py

# Voir les logs en direct
tail -f logs/bot.log

# Voir les offres en base
sqlite3 data/jobs.db "SELECT title, score, location, found_at FROM offers ORDER BY score DESC LIMIT 20;"
```

## Lancement automatique quotidien

### Linux / Mac (cron)

```bash
chmod +x schedule_cron.sh
crontab -e
# Ajouter : 30 7 * * * /chemin/complet/Job-search/schedule_cron.sh
```

### Windows (Planificateur de tâches)
Voir les instructions détaillées dans `schedule_cron.sh`.

## Comment fonctionne le scoring ?

Le bot attribue des points à chaque offre selon ce qu'il trouve dedans :

| Critère | Points |
|---|---|
| Mot-clé dans le **titre** | +4 par mot-clé |
| Mot-clé dans la description | +1 par mot-clé (max 3) |
| "Junior" / "débutant" / "reconversion" | +2 |
| Cybersécurité / SOC dans le titre | +3 |
| Télétravail / hybride | +1 |
| Alternance / apprentissage | +2 |
| 4+ ans d'expérience requis | -3 |

Les offres avec un score < 2 sont ignorées. Tu peux changer ces valeurs dans `config.yaml`.

## Anti-doublons

Chaque offre a un identifiant unique fourni par France Travail.
Avant de sauvegarder, le bot vérifie si cet ID est déjà en base.
Tu ne verras donc jamais la même offre deux fois dans tes emails.

## Roadmap

Voir [ROADMAP.md](ROADMAP.md) pour les versions futures (IA, génération LM/CV, interface web...).
