"""
Système de scoring : calcule la pertinence d'une offre d'emploi.

Principe : on lit le titre et la description de l'offre, et on
attribue des points selon ce qu'on y trouve. Plus le score est élevé,
plus l'offre correspond à ton profil.

C'est volontairement simple — pas d'IA pour l'instant.
On peut affiner les règles dans config.yaml sans toucher au code.
"""

import re
import logging
from bot.models import JobOffer

logger = logging.getLogger(__name__)

# Mots qui indiquent qu'une offre est accessible en reconversion / junior
JUNIOR_KEYWORDS = [
    "junior", "débutant", "débutante", "sans expérience",
    "profil junior", "première expérience", "premier emploi",
    "reconversion", "bac+2", "bts", "dut",
]

# Mots liés à la cybersécurité (bonus supplémentaire car c'est ton objectif)
CYBER_KEYWORDS = [
    "cybersécurité", "cyber", "soc", "siem", "splunk", "sentinel",
    "pentest", "sécurité informatique", "analyste sécurité",
    "threat", "incident response", "blue team",
]

# Mots liés au télétravail (bonus)
REMOTE_KEYWORDS = [
    "télétravail", "teletravail", "remote", "hybride",
    "travail à distance", "full remote",
]

# Patterns qui indiquent une expérience requise trop élevée (pénalité)
# Exemple : "4 ans d'expérience", "5 années d'expérience"
EXPERIENCE_PATTERNS = [
    r"\b([4-9]|\d{2,})\s*ans?\s+d[''e]expérience",
    r"expérience\s+de\s+([4-9]|\d{2,})\s*ans?",
    r"minimum\s+([4-9]|\d{2,})\s*ans?",
]


def normalize(text: str) -> str:
    """
    Met le texte en minuscules et supprime les accents pour comparer plus facilement.
    Ex : "Administrateur Système" → "administrateur systeme"
    """
    if not text:
        return ""
    text = text.lower()
    replacements = {
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'à': 'a', 'â': 'a', 'ä': 'a',
        'ù': 'u', 'û': 'u', 'ü': 'u',
        'ô': 'o', 'ö': 'o',
        'î': 'i', 'ï': 'i',
        'ç': 'c',
        "'": "'",
    }
    for accented, plain in replacements.items():
        text = text.replace(accented, plain)
    return text


def count_keyword_matches(text: str, keywords: list[str]) -> int:
    """
    Compte combien de mots-clés de la liste sont présents dans le texte.
    """
    text_norm = normalize(text)
    count = 0
    for kw in keywords:
        if normalize(kw) in text_norm:
            count += 1
    return count


def has_high_experience_requirement(text: str) -> bool:
    """
    Détecte si l'offre demande 4+ ans d'expérience.
    Dans ce cas, on pénalise le score (l'offre est moins accessible).
    """
    text_norm = normalize(text)
    for pattern in EXPERIENCE_PATTERNS:
        if re.search(pattern, text_norm):
            return True
    return False


def score_offer(offer: JobOffer, config: dict) -> int:
    """
    Calcule le score de pertinence d'une offre.

    Paramètres :
      - offer : l'offre à évaluer
      - config : le dict 'scoring' de config.yaml

    Retourne un entier (peut être négatif si l'offre est vraiment hors cible).
    """
    weights = config.get("weights", {})
    score = 0
    title = offer.title or ""
    description = offer.description or ""
    full_text = f"{title} {description}"

    # --- Mots-clés de recherche dans le TITRE (points forts) ---
    search_keywords = config.get("search_keywords", [])
    title_matches = count_keyword_matches(title, search_keywords)
    if title_matches > 0:
        points = title_matches * weights.get("title_keyword_match", 4)
        score += points
        logger.debug(f"  +{points} titre ({title_matches} mot(s)-clé)")

    # --- Mots-clés dans la DESCRIPTION ---
    desc_matches = count_keyword_matches(description, search_keywords)
    if desc_matches > 0:
        points = min(desc_matches, 3) * weights.get("desc_keyword_match", 1)
        score += points
        logger.debug(f"  +{points} description ({desc_matches} mot(s)-clé)")

    # --- Bonus junior / reconversion ---
    if count_keyword_matches(full_text, JUNIOR_KEYWORDS) > 0:
        points = weights.get("junior_bonus", 2)
        score += points
        logger.debug(f"  +{points} bonus junior")

    # --- Bonus cybersécurité ---
    if count_keyword_matches(title, CYBER_KEYWORDS) > 0:
        points = weights.get("cyber_bonus", 3)
        score += points
        logger.debug(f"  +{points} bonus cyber")

    # --- Bonus télétravail ---
    if count_keyword_matches(full_text, REMOTE_KEYWORDS) > 0:
        points = weights.get("remote_bonus", 1)
        score += points
        logger.debug(f"  +{points} bonus télétravail")

    # --- Bonus alternance ---
    if offer.contract and "ALT" in offer.contract.upper():
        points = weights.get("alternance_bonus", 2)
        score += points
        logger.debug(f"  +{points} bonus alternance")
    elif count_keyword_matches(full_text, ["alternance", "apprentissage"]) > 0:
        points = weights.get("alternance_bonus", 2)
        score += points
        logger.debug(f"  +{points} bonus alternance (description)")

    # --- Pénalité expérience trop élevée ---
    if has_high_experience_requirement(full_text):
        penalty = weights.get("experience_penalty", -3)
        score += penalty
        logger.debug(f"  {penalty} pénalité expérience requise")

    logger.debug(f"Score final '{title}' : {score}")
    return score


def filter_and_score_offers(offers: list, config: dict) -> list:
    """
    Applique le scoring à toutes les offres et filtre celles sous le seuil minimum.

    Retourne les offres triées par score décroissant.
    """
    min_score = config.get("min_score", 2)
    # On passe les mots-clés au scorer pour qu'il puisse les utiliser
    scoring_config = dict(config)
    scoring_config["search_keywords"] = config.get("search_keywords", [])

    scored_offers = []
    for offer in offers:
        offer.score = score_offer(offer, scoring_config)
        if offer.score >= min_score:
            scored_offers.append(offer)

    scored_offers.sort(key=lambda o: o.score, reverse=True)
    logger.info(
        f"Scoring : {len(scored_offers)}/{len(offers)} offres "
        f"retenues (score >= {min_score})"
    )
    return scored_offers
