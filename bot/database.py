"""
Gestion de la base de données SQLite.

V3 : ajout de la gestion des statuts, des filtres avancés
     et des statistiques pour l'interface Streamlit.

Anti-doublon sur deux niveaux :
  1. ID source (ft_123, adzuna_456...) — même source
  2. content_hash(titre + société + lieu) — cross-source
"""

import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from bot.models import JobOffer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Statuts possibles pour une offre
# Ces valeurs correspondent au cycle de vie d'une candidature
# ---------------------------------------------------------------------------
STATUS_LABELS: dict[str, str] = {
    "new":        "🆕 Nouvelle",
    "to_review":  "👁️ À étudier",
    "interested": "⭐ Intéressante",
    "ignored":    "🚫 Ignorée",
    "prepared":   "📝 Candidature préparée",
    "applied":    "📤 Postulée",
    "follow_up":  "🔔 Relance à faire",
    "rejected":   "❌ Refusée",
}

VALID_STATUSES = set(STATUS_LABELS.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return (text or "").lower().strip()


def compute_content_hash(
    title: str, company: str = "", location: str = ""
) -> str:
    """
    Hash MD5 du contenu pour détecter les doublons cross-source.

    Même offre publiée par France Travail ET Adzuna → même hash → un seul
    enregistrement en base. MD5 n'est pas sécurisé en crypto mais c'est
    parfait ici pour une empreinte rapide.
    """
    key = "|".join([_norm(title), _norm(company), _norm(location)])
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL permet à un lecteur et un écrivain de coexister sans blocage.
    # Nécessaire car Streamlit et le thread bot accèdent à la DB en parallèle.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Initialisation / migration
# ---------------------------------------------------------------------------

def init_database(db_path: str) -> None:
    """
    Crée la table et les index. Compatible avec les bases V1 et V2
    grâce aux ALTER TABLE sécurisés (ignorés si colonne déjà présente).
    """
    conn = get_connection(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id           TEXT PRIMARY KEY,
                content_hash TEXT,
                title        TEXT NOT NULL,
                company      TEXT,
                location     TEXT,
                contract     TEXT,
                salary       TEXT,
                description  TEXT,
                url          TEXT,
                source       TEXT,
                score        INTEGER DEFAULT 0,
                published_at TEXT,
                found_at     TEXT NOT NULL,
                applied      INTEGER DEFAULT 0,
                status       TEXT DEFAULT 'new'
            )
        """)

        # Migrations douces : colonnes ajoutées en V2/V3
        for col_sql in [
            "ALTER TABLE offers ADD COLUMN content_hash TEXT",
            "ALTER TABLE offers ADD COLUMN status TEXT DEFAULT 'new'",
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass  # Colonne déjà présente

        # Index pour accélérer les recherches
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_content_hash "
            "ON offers(content_hash)",
            "CREATE INDEX IF NOT EXISTS idx_status "
            "ON offers(status)",
            "CREATE INDEX IF NOT EXISTS idx_score "
            "ON offers(score DESC)",
            "CREATE INDEX IF NOT EXISTS idx_found_at "
            "ON offers(found_at DESC)",
        ]:
            conn.execute(idx_sql)

        conn.commit()
        logger.info(f"Base de données prête : {db_path}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Anti-doublon
# ---------------------------------------------------------------------------

def offer_exists(db_path: str, offer: "JobOffer") -> bool:
    """
    Doublon sur deux niveaux :
      1. Même ID source (certitude absolue)
      2. Même hash titre/société/lieu (probable doublon cross-source)
    """
    conn = get_connection(db_path)
    try:
        # Niveau 1 : ID exact
        row = conn.execute(
            "SELECT 1 FROM offers WHERE id = ?", (offer.id,)
        ).fetchone()
        if row:
            logger.debug(f"Doublon ID : {offer.id}")
            return True

        # Niveau 2 : contenu similaire
        h = compute_content_hash(
            offer.title, offer.company or "", offer.location or ""
        )
        row = conn.execute(
            "SELECT 1 FROM offers WHERE content_hash = ?", (h,)
        ).fetchone()
        if row:
            logger.debug(
                f"Doublon hash : '{offer.title}' @ {offer.company}"
            )
            return True

        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------

def save_offer(db_path: str, offer: "JobOffer") -> bool:
    """Retourne True si nouvelle offre sauvegardée."""
    if offer_exists(db_path, offer):
        return False

    content_hash = compute_content_hash(
        offer.title, offer.company or "", offer.location or ""
    )
    conn = get_connection(db_path)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO offers
                (id, content_hash, title, company, location, contract,
                 salary, description, url, source, score,
                 published_at, found_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
        """, (
            offer.id, content_hash, offer.title, offer.company,
            offer.location, offer.contract, offer.salary,
            offer.description, offer.url, offer.source, offer.score,
            offer.published_at, datetime.now().isoformat(),
        ))
        conn.commit()
        return True
    finally:
        conn.close()


def save_offers(db_path: str, offers: list) -> tuple[int, list]:
    """
    Sauvegarde une liste d'offres en une seule transaction.
    Retourne (nombre de nouvelles offres insérées, liste des nouvelles offres).
    """
    if not offers:
        return 0, []

    conn = get_connection(db_path)
    new_count = 0
    new_offers: list = []
    try:
        for offer in offers:
            # Niveau 1 : ID exact
            if conn.execute(
                "SELECT 1 FROM offers WHERE id = ?", (offer.id,)
            ).fetchone():
                continue

            # Niveau 2 : hash contenu
            h = compute_content_hash(
                offer.title, offer.company or "", offer.location or ""
            )
            if conn.execute(
                "SELECT 1 FROM offers WHERE content_hash = ?", (h,)
            ).fetchone():
                continue

            conn.execute("""
                INSERT OR IGNORE INTO offers
                    (id, content_hash, title, company, location, contract,
                     salary, description, url, source, score,
                     published_at, found_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
            """, (
                offer.id, h, offer.title, offer.company,
                offer.location, offer.contract, offer.salary,
                offer.description, offer.url, offer.source, offer.score,
                offer.published_at, datetime.now().isoformat(),
            ))
            new_count += 1
            new_offers.append(offer)

        conn.commit()
    finally:
        conn.close()

    logger.info(
        f"{new_count}/{len(offers)} nouvelles offres sauvegardées"
    )
    return new_count, new_offers


def update_offer_status(
    db_path: str, offer_id: str, status: str
) -> None:
    """
    Met à jour le statut d'une offre.

    Le statut suit le cycle de vie d'une candidature :
    new → to_review → interested → prepared → applied → follow_up → rejected

    On met aussi à jour 'applied' (1/0) pour rétrocompatibilité.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Statut invalide : '{status}'. "
            f"Valeurs possibles : {list(VALID_STATUSES)}"
        )
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE offers SET status = ?, applied = ? WHERE id = ?",
            (status, 1 if status == "applied" else 0, offer_id),
        )
        conn.commit()
        logger.debug(f"Statut mis à jour : {offer_id} → {status}")
    finally:
        conn.close()


def update_offers_status_batch(
    db_path: str, updates: dict[str, str]
) -> int:
    """
    Met à jour plusieurs statuts en une seule transaction.
    updates = {offer_id: new_status, ...}
    Retourne le nombre de lignes modifiées.
    """
    conn = get_connection(db_path)
    count = 0
    try:
        for offer_id, status in updates.items():
            if status in VALID_STATUSES:
                conn.execute(
                    "UPDATE offers SET status = ?, applied = ? "
                    "WHERE id = ?",
                    (status, 1 if status == "applied" else 0, offer_id),
                )
                count += 1
        conn.commit()
        logger.info(f"{count} statut(s) mis à jour")
        return count
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def get_recent_offers(
    db_path: str, days: int = 1, min_score: int = 0
) -> list:
    """Offres trouvées dans les N derniers jours, pour le rapport email."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute("""
            SELECT * FROM offers
            WHERE found_at >= datetime('now', ?)
              AND score >= ?
            ORDER BY score DESC, published_at DESC
        """, (f"-{days} days", min_score)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_offers_filtered(
    db_path: str,
    sources: list[str] = None,
    statuses: list[str] = None,
    min_score: int = 0,
    location_kw: str = "",
    search_kw: str = "",
    limit: int = 300,
    offset: int = 0,
) -> list[dict]:
    """
    Récupère les offres avec filtres pour l'interface Streamlit.

    Paramètres :
      - sources     : filtrer sur certaines sources (ex. ["france_travail"])
      - statuses    : filtrer sur certains statuts (ex. ["new", "interested"])
      - min_score   : score minimum
      - location_kw : mot-clé dans le lieu (ex. "Toulouse")
      - search_kw   : mot-clé dans titre, description ou société
    """
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM offers WHERE score >= ?"
        params: list = [min_score]

        if sources:
            # LIKE pour matcher aussi "email_alert:linkedin"
            clauses = " OR ".join(
                "source LIKE ?" for _ in sources
            )
            query += f" AND ({clauses})"
            params.extend(f"%{s}%" for s in sources)

        if statuses:
            ph = ",".join("?" * len(statuses))
            query += f" AND status IN ({ph})"
            params.extend(statuses)

        if location_kw:
            query += " AND location LIKE ?"
            params.append(f"%{location_kw}%")

        if search_kw:
            query += (
                " AND (title LIKE ? OR description LIKE ? "
                "OR company LIKE ?)"
            )
            params.extend([f"%{search_kw}%"] * 3)

        query += (
            " ORDER BY score DESC, found_at DESC"
            f" LIMIT {int(limit)} OFFSET {int(offset)}"
        )

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_stats(db_path: str) -> dict:
    """Statistiques de base (compatibilité main.py)."""
    conn = get_connection(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM offers"
        ).fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE found_at >= date('now')"
        ).fetchone()[0]
        applied = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE applied = 1"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT source, COUNT(*) as n FROM offers "
            "GROUP BY source ORDER BY n DESC"
        ).fetchall()
        return {
            "total": total,
            "today": today,
            "applied": applied,
            "by_source": {r["source"]: r["n"] for r in rows},
        }
    finally:
        conn.close()


def get_advanced_stats(db_path: str) -> dict:
    """
    Statistiques avancées pour le dashboard Streamlit.

    Retourne :
      - total         : nombre total d'offres
      - by_status     : {statut: count}
      - by_source     : [{source, n, avg_score, max_score}]
      - score_dist    : [{range, n}] — distribution des scores
      - timeline      : [{day, n}] — offres par jour sur 14 jours
    """
    conn = get_connection(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM offers"
        ).fetchone()[0]

        rows = conn.execute(
            "SELECT status, COUNT(*) as n "
            "FROM offers GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["n"] for r in rows}

        rows = conn.execute("""
            SELECT source,
                   COUNT(*) as n,
                   ROUND(AVG(score), 1) as avg_score,
                   MAX(score) as max_score
            FROM offers
            GROUP BY source
            ORDER BY n DESC
        """).fetchall()
        by_source = [dict(r) for r in rows]

        rows = conn.execute("""
            SELECT
                CASE
                    WHEN score >= 10 THEN '10+'
                    WHEN score >= 8  THEN '8-9'
                    WHEN score >= 6  THEN '6-7'
                    WHEN score >= 4  THEN '4-5'
                    ELSE '1-3'
                END as range,
                COUNT(*) as n
            FROM offers
            GROUP BY range
            ORDER BY range DESC
        """).fetchall()
        score_dist = [dict(r) for r in rows]

        rows = conn.execute("""
            SELECT DATE(found_at) as day, COUNT(*) as n
            FROM offers
            WHERE found_at >= date('now', '-14 days')
            GROUP BY day ORDER BY day
        """).fetchall()
        timeline = [dict(r) for r in rows]

        return {
            "total": total,
            "by_status": by_status,
            "by_source": by_source,
            "score_dist": score_dist,
            "timeline": timeline,
        }
    finally:
        conn.close()


def get_all_sources(db_path: str) -> list[str]:
    """Liste des sources présentes en base (pour les filtres UI)."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT source FROM offers ORDER BY source"
        ).fetchall()
        return [r["source"] for r in rows if r["source"]]
    finally:
        conn.close()
