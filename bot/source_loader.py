"""
Chargeur de sources.

Ce module lit config.yaml pour savoir quelles sources sont activées,
les instancie, vérifie qu'elles sont disponibles (clés API présentes),
et retourne une liste prête à l'emploi.

Ajouter une nouvelle source = 4 lignes ici + créer son fichier dans sources/.

Gestion des erreurs :
  Si une source plante pendant la recherche, le bot log l'erreur
  et continue avec les autres sources. On ne perd jamais toute la session
  à cause d'une seule API défaillante.
"""

import logging
import time
from typing import Optional

from bot.models import JobOffer
from bot.sources.base import JobSource
from bot.sources.france_travail import FranceTravailSource
from bot.sources.adzuna import AdzunaSource
from bot.sources.jooble import JoobleSource
from bot.sources.careerjet import CareerjetSource
from bot.sources.themuse import TheMuseSource
from bot.sources.brave_search import BraveSearchSource

logger = logging.getLogger(__name__)

_SEP = "─" * 54

# Registre : nom dans config.yaml → classe Python
SOURCE_REGISTRY: dict[str, type[JobSource]] = {
    "france_travail": FranceTravailSource,
    "adzuna": AdzunaSource,
    "jooble": JoobleSource,
    "careerjet": CareerjetSource,
    "themuse": TheMuseSource,
    "brave_search": BraveSearchSource,
}


def load_sources(config: dict) -> list[JobSource]:
    """
    Charge et retourne les sources actives et disponibles.

    Une source est chargée si :
      1. Elle est dans SOURCE_REGISTRY
      2. Elle est marquée enabled: true dans config.yaml
      3. is_available() retourne True (clés API présentes)
    """
    sources_cfg = config.get("sources", {})
    active: list[JobSource] = []

    for name, cls in SOURCE_REGISTRY.items():
        src_cfg = sources_cfg.get(name, {})

        # Par défaut, france_travail est activée, les autres non
        default_enabled = name == "france_travail"
        if not src_cfg.get("enabled", default_enabled):
            logger.debug(f"Source désactivée : {name}")
            continue

        source = cls(config)
        if not source.is_available():
            logger.warning(
                f"Source '{name}' activée mais non disponible "
                f"(clés API manquantes dans .env)"
            )
            continue

        active.append(source)
        logger.info(f"Source chargée : {name}")

    if not active:
        logger.error(
            "Aucune source disponible ! "
            "Vérifie les clés API dans .env et config.yaml"
        )

    return active


def _log_source_summary(
    name: str, stats: dict, elapsed: float
) -> None:
    req = stats.get("requests", 0)
    ok = stats.get("success", 0)
    no_r = stats.get("no_results", 0)
    err = stats.get("errors", 0)
    n = stats.get("offers", 0)
    codes = stats.get("error_codes", "")
    diag = stats.get("diagnosis", "")

    mark = "✓" if not err else "✗"
    parts = [
        f"{mark} {name:<20}",
        f"{req:>3} req",
        f"{ok:>3} ok",
    ]
    if no_r:
        parts.append(f"{no_r:>3} sans résultat")
    parts += [f"{err:>3} err", f"{n:>4} offres", f"{elapsed:.1f}s"]
    logger.info("  ".join(parts))
    if err and (codes or diag):
        detail = (
            f"{codes} — {diag}" if (codes and diag) else codes or diag
        )
        logger.warning(f"  └─ {detail[:120]}")


def fetch_all_sources(
    sources: list[JobSource],
    keywords: list[str],
    locations: list[dict],
) -> tuple[list[JobOffer], dict[str, int], list[str]]:
    """
    Lance la recherche sur toutes les sources.

    Retourne :
      - La liste complète des offres (toutes sources confondues)
      - Un dict {nom_source: nb_offres} pour le résumé email
      - Une liste des noms de sources qui ont levé une exception
    """
    all_offers: list[JobOffer] = []
    counts: dict[str, int] = {}
    failed: list[str] = []

    logger.info(_SEP)
    for source in sources:
        start = time.time()
        try:
            offers = source.search(keywords, locations)
            elapsed = time.time() - start
            counts[source.name] = len(offers)
            all_offers.extend(offers)
            _log_source_summary(source.name, source.stats, elapsed)
        except Exception as e:
            elapsed = time.time() - start
            counts[source.name] = 0
            failed.append(source.name)
            logger.error(
                f"✗ {source.name} a planté après {elapsed:.1f}s : {e}",
                exc_info=True,
            )
    logger.info(_SEP)
    logger.info(
        f"Total : {len(all_offers)} offres brutes "
        f"sur {len(sources)} source(s)"
    )
    return all_offers, counts, failed
