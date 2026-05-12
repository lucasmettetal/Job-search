"""
Point d'entrée du bot de recherche d'emploi — V2 multi-sources.

Pipeline :
  1. Charger config.yaml et les variables .env
  2. Initialiser la base SQLite
  3. Charger toutes les sources activées (source_loader)
  4. Interroger chaque source → liste d'offres brutes
  5. Scorer les offres (pertinence)
  6. Sauvegarder les nouvelles offres (anti-doublon ID + hash)
  7. Générer le rapport groupé par source
  8. Envoyer l'email
"""

import json
import logging
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from bot.database import (
    init_database, save_offers, get_recent_offers, get_stats
)
from bot.scoring import filter_and_score_offers
from bot.source_loader import load_sources, fetch_all_sources
from bot.report import generate_html_report, generate_text_report
from bot.mailer import send_report
from bot.models import JobOffer


def setup_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    verbose = log_cfg.get("verbose", False)
    log_file = log_cfg.get("file", "logs/bot.log")
    debug_file = log_cfg.get("debug_file", "")

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(formatter)

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    main_fh = logging.FileHandler(log_file, encoding="utf-8")
    main_fh.setLevel(logging.INFO)
    main_fh.setFormatter(formatter)

    handlers: list[logging.Handler] = [console, main_fh]

    if debug_file:
        Path(debug_file).parent.mkdir(parents=True, exist_ok=True)
        dbg_fh = logging.FileHandler(
            debug_file, encoding="utf-8", mode="w"
        )
        dbg_fh.setLevel(logging.DEBUG)
        dbg_fh.setFormatter(formatter)
        handlers.append(dbg_fh)

    logging.basicConfig(level=logging.DEBUG, handlers=handlers)


def load_config(path: str = "config.yaml") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(
            f"[ERREUR] Fichier '{path}' introuvable.\n"
            "  → Lance l'interface pour créer la config :\n"
            "      streamlit run app.py\n"
            "  → ou copie et adapte config.yaml manuellement",
            file=sys.stderr,
        )
        sys.exit(1)


def rows_to_offers(rows: list[dict]) -> list[JobOffer]:
    """Reconvertit les lignes SQLite en objets JobOffer pour le rapport."""
    return [
        JobOffer(
            id=r["id"],
            title=r["title"],
            source=r["source"],
            url=r["url"],
            company=r["company"],
            location=r["location"],
            contract=r["contract"],
            salary=r["salary"],
            description=r["description"],
            published_at=r["published_at"],
            score=r["score"],
        )
        for r in rows
    ]


def run(config: dict) -> None:
    logger = logging.getLogger(__name__)
    sep = "=" * 55
    _run_start = time.time()

    logger.info(sep)
    logger.info("  JobBot V2 — Démarrage")
    logger.info(sep)

    db_path = config.get("database", {}).get("path", "data/jobs.db")
    search_cfg = config.get("search", {})
    keywords = search_cfg.get("keywords", [])
    locations = search_cfg.get("locations", [])

    # 1. Base de données
    init_database(db_path)

    # 2. Charger les sources activées
    sources = load_sources(config)
    if not sources:
        logger.error("Aucune source disponible. Arrêt.")
        return

    logger.info(
        f"Sources actives : "
        f"{', '.join(s.name for s in sources)}"
    )

    # 3. Récupérer toutes les offres
    # fetch_all_sources retourne aussi le nb d'offres par source
    raw_offers, source_counts, failed_sources = fetch_all_sources(
        sources, keywords, locations
    )

    if not raw_offers:
        logger.warning("Aucune offre récupérée sur aucune source.")
        return

    # 4. Scorer et filtrer
    scoring_cfg = dict(config.get("scoring", {}))
    scoring_cfg["search_keywords"] = keywords
    scored = filter_and_score_offers(raw_offers, scoring_cfg)
    logger.info(f"Après scoring : {len(scored)} offres pertinentes")

    # 5. Sauvegarder (anti-doublon ID + hash)
    new_count, new_offers_list = save_offers(db_path, scored)
    logger.info(f"Nouvelles offres en base : {new_count}")

    # 6. Récupérer les offres récentes pour le rapport
    min_score = config.get("scoring", {}).get("min_score", 2)
    recent_rows = get_recent_offers(
        db_path, days=1, min_score=min_score
    )
    stats = get_stats(db_path)

    logger.info(f"Offres dans le rapport : {len(recent_rows)}")
    logger.info(
        f"Stats base — total:{stats['total']} "
        f"aujourd'hui:{stats['today']} "
        f"candidatures:{stats['applied']}"
    )

    # Résumé par source dans les logs
    if stats.get("by_source"):
        logger.info("Répartition en base par source :")
        for src, n in stats["by_source"].items():
            logger.info(f"  {src:<22} {n} offres")

    # 7. Générer le rapport
    # On passe source_counts (offres récupérées CE matin, pas le total)
    recent_offers = rows_to_offers(recent_rows)
    html_body = generate_html_report(
        recent_offers, stats, config, source_counts
    )
    text_body = generate_text_report(
        recent_offers, stats, config, source_counts
    )

    # 8. Envoyer l'email
    email_sent = send_report(
        html_body=html_body,
        text_body=text_body,
        nb_offers=len(recent_offers),
        config=config.get("email", {}),
    )

    # Résumé JSON pour l'interface Streamlit
    _preview = [
        {
            "title": o.title,
            "company": o.company or "",
            "location": o.location or "",
            "source": o.source,
            "score": o.score or 0,
            "url": o.url or "",
            "published_at": o.published_at or "",
        }
        for o in new_offers_list[:20]
    ]
    _result = {
        "success": True,
        "duration": round(time.time() - _run_start, 1),
        "new_offers": new_count,
        "total_found": sum(source_counts.values()),
        "in_report": len(recent_rows),
        "sources": {s.name: s.stats for s in sources},
        "new_offers_preview": _preview,
    }
    try:
        _result_path = Path(db_path).parent / "last_run.json"
        _result_path.parent.mkdir(parents=True, exist_ok=True)
        _result_path.write_text(
            json.dumps(_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass

    logger.info(sep)
    status = "Email envoyé ✓" if email_sent else "Email non envoyé"
    logger.info(
        f"  Terminé — {new_count} nouvelles offres — {status}"
    )
    if failed_sources:
        logger.warning(
            f"  Sources en erreur : {', '.join(failed_sources)}"
        )
    logger.info(sep)


if __name__ == "__main__":
    # load_dotenv() doit s'exécuter avant run() mais après les imports.
    # Les sources lisent os.getenv() dans __init__(), pas à l'import.
    load_dotenv()
    config = load_config("config.yaml")
    setup_logging(config)
    run(config)
