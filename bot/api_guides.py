"""
Guides d'intégration pour chaque service API.

Utilisé par la page "Clés API" de l'interface Streamlit pour afficher
des tutoriels directement dans l'interface, sans consulter de documentation externe.

Structure de chaque guide :
  title          : nom affiché
  emoji          : icône
  purpose        : à quoi sert cette source (2-3 phrases)
  recommended    : True si fortement recommandée
  needs_key      : True si une clé API est requise
  free           : True si le plan gratuit suffit
  status_note    : ligne courte affichée sous le titre
  env_vars       : liste des variables .env à renseigner
  signup_url     : URL officielle pour créer un compte / obtenir la clé
  steps          : étapes numérotées pour configurer la source
  common_errors  : liste de (titre_erreur, solution)
"""

API_GUIDES: dict[str, dict] = {

    # ------------------------------------------------------------------
    # France Travail
    # ------------------------------------------------------------------
    "france_travail": {
        "title": "France Travail",
        "emoji": "🇫🇷",
        "purpose": (
            "Source principale pour les offres françaises. "
            "API officielle ex-Pôle Emploi — la base la plus complète pour "
            "les postes en Occitanie. Gratuite, sans limite de quota."
        ),
        "recommended": True,
        "needs_key": True,
        "free": True,
        "status_note": "Gratuite — inscription requise",
        "env_vars": [
            "FRANCE_TRAVAIL_CLIENT_ID",
            "FRANCE_TRAVAIL_CLIENT_SECRET",
        ],
        "signup_url": "https://francetravail.io/inscription",
        "steps": [
            "Va sur **francetravail.io/inscription** et crée un compte développeur.",
            "Clique sur **« Créer une application »** et donne-lui un nom (ex. : JobBot).",
            "Dans la liste des services de l'application, "
            "active **« Offres d'emploi v2 »** — il n'est pas activé par défaut.",
            "Ouvre les détails de l'application : "
            "copie le **Client ID** (long identifiant) et le **Client Secret**.",
            "Colle ces deux valeurs dans les champs ci-dessous, puis clique Sauvegarder.",
        ],
        "common_errors": [
            (
                "401 Unauthorized",
                "Client ID ou Client Secret incorrect. "
                "Vérifie l'absence d'espaces en début ou fin de valeur.",
            ),
            (
                "Service 'Offres d'emploi v2' non activé",
                "Dans francetravail.io → ton application → Services, "
                "assure-toi que 'Offres d'emploi v2' est bien coché.",
            ),
            (
                "Token expiré rapidement",
                "Le bot renouvelle le token automatiquement. "
                "Si l'erreur persiste, vérifie que l'application n'a pas été "
                "suspendue sur francetravail.io.",
            ),
        ],
    },

    # ------------------------------------------------------------------
    # Adzuna
    # ------------------------------------------------------------------
    "adzuna": {
        "title": "Adzuna",
        "emoji": "🔍",
        "purpose": (
            "Agrégateur international avec bonne couverture France. "
            "Complète France Travail en ajoutant des offres d'Indeed, JobTeaser, etc. "
            "Quota : 250 requêtes/jour — largement suffisant pour un lancement quotidien."
        ),
        "recommended": False,
        "needs_key": True,
        "free": True,
        "status_note": "Gratuite — 250 req/jour",
        "env_vars": ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"],
        "signup_url": "https://developer.adzuna.com/signup",
        "steps": [
            "Va sur **developer.adzuna.com/signup** et crée un compte.",
            "Vérifie ton email de confirmation, puis connecte-toi.",
            "Va dans **« My Apps »** et clique **« Register a New App »**.",
            "Renseigne un nom (ex. : JobBot) et une URL "
            "(http://localhost convient parfaitement).",
            "L'**App ID** (un nombre) et l'**App Key** "
            "(chaîne alphanumérique) apparaissent dans la liste.",
            "Colle ces deux valeurs dans les champs ci-dessous.",
        ],
        "common_errors": [
            (
                "401 Unauthorized",
                "App ID ou App Key invalide. "
                "L'App ID est un nombre entier (ex. : 12345678), "
                "l'App Key une longue chaîne de lettres et chiffres.",
            ),
            (
                "429 Too Many Requests",
                "Quota journalier dépassé (250 req). "
                "Réduis max_results_per_keyword dans la page Sources.",
            ),
            (
                "0 résultats",
                "Normal si le bot tourne plusieurs fois le même jour. "
                "Les offres sont déjà en base — les doublons sont filtrés.",
            ),
        ],
    },

    # ------------------------------------------------------------------
    # Jooble
    # ------------------------------------------------------------------
    "jooble": {
        "title": "Jooble",
        "emoji": "🌐",
        "purpose": (
            "Agrégateur mondial indexant des centaines de sites emploi français. "
            "Utile pour toucher des offres non présentes sur France Travail ou Adzuna. "
            "Quota limité (~500 req/mois) — le bot regroupe les mots-clés "
            "pour en consommer le moins possible."
        ),
        "recommended": False,
        "needs_key": True,
        "free": True,
        "status_note": "Gratuite — ~500 req/mois",
        "env_vars": ["JOOBLE_API_KEY"],
        "signup_url": "https://jooble.org/api/about",
        "steps": [
            "Va sur **jooble.org/api/about**.",
            "Clique sur **« Get API key »** ou remplis le formulaire de contact en bas.",
            "Indique ton nom, ton email et une description de l'usage "
            "(ex. : 'Bot personnel de veille emploi, usage non commercial').",
            "Jooble envoie la clé par email sous **24 à 48h**.",
            "Colle la clé reçue dans le champ ci-dessous.",
        ],
        "common_errors": [
            (
                "Pas de réponse après 48h",
                "Renvoie le formulaire avec une description plus détaillée. "
                "Précise que l'usage est personnel et non commercial.",
            ),
            (
                "403 Forbidden",
                "Clé invalide ou désactivée. "
                "Vérifie l'email reçu de Jooble pour copier la bonne clé.",
            ),
            (
                "Quota dépassé",
                "Réduis max_results_per_keyword à 10 dans la page Sources "
                "pour économiser les requêtes.",
            ),
        ],
    },

    # ------------------------------------------------------------------
    # Brave Search
    # ------------------------------------------------------------------
    "brave_search": {
        "title": "Brave Search",
        "emoji": "🦁",
        "purpose": (
            "Moteur de recherche indépendant. Le bot construit des requêtes ciblées "
            "(ex. : \"SOC junior\" toulouse site:apec.fr) pour trouver des offres "
            "sur n'importe quel site, y compris ceux sans API. "
            "Idéal pour compléter les sources classiques."
        ),
        "recommended": False,
        "needs_key": True,
        "free": True,
        "status_note": "Gratuite — 2 000 req/mois",
        "env_vars": ["BRAVE_API_KEY"],
        "signup_url": "https://api.search.brave.com/register",
        "steps": [
            "Va sur **api.search.brave.com/register** et crée un compte.",
            "Vérifie ton email de confirmation.",
            "Sélectionne le plan **Free** "
            "(2 000 req/mois, sans carte bancaire requise).",
            "Dans ton tableau de bord, va dans **« API Keys »** "
            "et copie ta clé.",
            "Colle la clé dans le champ ci-dessous.",
        ],
        "common_errors": [
            (
                "401 Unauthorized",
                "Clé incorrecte ou expirée. "
                "Régénère-en une nouvelle depuis le tableau de bord Brave.",
            ),
            (
                "429 Too Many Requests",
                "Quota mensuel dépassé (2 000 req). "
                "Désactive temporairement la source depuis la page Sources.",
            ),
        ],
    },

    # ------------------------------------------------------------------
    # Email SMTP (rapport quotidien)
    # ------------------------------------------------------------------
    "email_smtp": {
        "title": "Gmail — rapport quotidien",
        "emoji": "📤",
        "purpose": (
            "Permet au bot d'envoyer le résumé des offres par email chaque matin. "
            "Entièrement optionnel : si non configuré, le bot tourne normalement "
            "mais n'envoie aucun email. Fonctionne uniquement avec Gmail."
        ),
        "recommended": False,
        "needs_key": True,
        "free": True,
        "status_note": "Optionnel — Gmail uniquement",
        "env_vars": ["EMAIL_SENDER", "EMAIL_APP_PASSWORD"],
        "signup_url": "https://myaccount.google.com/apppasswords",
        "steps": [
            "Active la **validation en 2 étapes** sur ton compte Google "
            "(Compte Google → Sécurité → Validation en 2 étapes).",
            "Va sur **myaccount.google.com/apppasswords**.",
            "Choisis **« Autre (nom personnalisé) »** et tape « JobBot ».",
            "Google génère un **mot de passe de 16 caractères** — "
            "c'est cette valeur à copier, pas ton vrai mot de passe Gmail.",
            "Dans les champs ci-dessous : ton adresse Gmail complète, "
            "puis le mot de passe de 16 caractères.",
        ],
        "common_errors": [
            (
                "535 Authentication Failed",
                "Tu utilises ton vrai mot de passe Gmail. "
                "Il faut obligatoirement un mot de passe d'application (16 car.).",
            ),
            (
                "La page /apppasswords n'existe pas",
                "La validation en 2 étapes n'est pas activée. "
                "Active-la d'abord dans Compte Google → Sécurité.",
            ),
            (
                "Email reçu dans les spams",
                "Normal pour les premiers envois. "
                "Marque l'email comme « Pas un spam » — les suivants arriveront en boîte.",
            ),
        ],
    },

    # ------------------------------------------------------------------
    # IMAP (alertes email emploi)
    # ------------------------------------------------------------------
    "email_alerts": {
        "title": "Gmail / IMAP — alertes emploi",
        "emoji": "📧",
        "purpose": (
            "Lit les emails d'alerte emploi reçus dans ta boîte "
            "(LinkedIn, Indeed, HelloWork, WTTJ, APEC…) et extrait les offres. "
            "100% légal — aucun scraping. "
            "Utile si tu as déjà configuré des alertes emploi sur ces plateformes."
        ),
        "recommended": False,
        "needs_key": True,
        "free": True,
        "status_note": "Optionnel — IMAP doit être activé",
        "env_vars": ["IMAP_EMAIL", "IMAP_PASSWORD"],
        "signup_url": (
            "https://mail.google.com/mail/u/0/#settings/fwdandpop"
        ),
        "steps": [
            "Active **IMAP dans Gmail** : Gmail → ⚙️ Paramètres → "
            "« Voir tous les paramètres » → onglet « Transfert et POP/IMAP » "
            "→ Activer IMAP → Enregistrer.",
            "Crée un **mot de passe d'application** Gmail "
            "(même procédure que l'SMTP ci-dessus — ou réutilise le même).",
            "Renseigne ton adresse Gmail et ce mot de passe dans les champs ci-dessous. "
            "Le serveur IMAP est auto-détecté pour Gmail, Outlook, Orange, Free…",
            "Pour un fournisseur non reconnu, renseigne manuellement **IMAP_HOST** "
            "(ex. : imap.mondomaine.fr).",
            "Configure des alertes emploi sur LinkedIn / Indeed / HelloWork "
            "pour recevoir des emails que le bot pourra lire.",
        ],
        "common_errors": [
            (
                "Authentication failed",
                "Utilise un mot de passe d'application Gmail (16 car.), "
                "pas ton vrai mot de passe. "
                "Google bloque IMAP avec le mot de passe normal.",
            ),
            (
                "Connexion refusée",
                "IMAP n'est pas activé dans les paramètres Gmail. "
                "Suis l'étape 1 ci-dessus.",
            ),
            (
                "Domaine IMAP non reconnu",
                "Pour les fournisseurs inconnus (autre que Gmail/Outlook/Orange/Free…), "
                "renseigne manuellement le champ IMAP_HOST.",
            ),
        ],
    },

    # ------------------------------------------------------------------
    # Careerjet (clé optionnelle)
    # ------------------------------------------------------------------
    "careerjet": {
        "title": "Careerjet",
        "emoji": "📋",
        "purpose": (
            "API publique gratuite, sans inscription requise. "
            "Active-la directement depuis la page Sources — aucune clé nécessaire. "
            "L'ID affilié ci-dessous est entièrement optionnel "
            "(uniquement pour les partenaires officiels Careerjet)."
        ),
        "recommended": False,
        "needs_key": False,
        "free": True,
        "status_note": "Fonctionne sans clé — prêt à l'emploi",
        "env_vars": [],
        "signup_url": "",
        "steps": [
            "Aucune configuration requise.",
            "Active la source depuis la page **Sources**.",
            "(Optionnel) Si tu es partenaire Careerjet, "
            "renseigne ton ID affilié ci-dessous.",
        ],
        "common_errors": [
            (
                "0 résultats",
                "Careerjet peut retourner 0 résultats pour des mots-clés très spécifiques. "
                "Essaie des termes plus généraux.",
            ),
        ],
    },

    # ------------------------------------------------------------------
    # The Muse (aucune clé)
    # ------------------------------------------------------------------
    "themuse": {
        "title": "The Muse",
        "emoji": "✨",
        "purpose": (
            "API publique entièrement gratuite, sans inscription. "
            "Spécialisée dans les offres de startups et entreprises tech — "
            "principalement aux États-Unis. "
            "Surtout utile si tu cherches des postes remote internationaux."
        ),
        "recommended": False,
        "needs_key": False,
        "free": True,
        "status_note": "Fonctionne sans clé — prêt à l'emploi",
        "env_vars": [],
        "signup_url": "",
        "steps": [
            "Aucune configuration requise.",
            "Active la source depuis la page **Sources**.",
        ],
        "common_errors": [
            (
                "Peu d'offres françaises",
                "The Muse est principalement américaine. "
                "Elle est utile uniquement pour du remote international.",
            ),
        ],
    },
}
