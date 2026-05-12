"""
JobBot — Interface web locale (Streamlit)
Lance avec : streamlit run app.py
             ou double-clic sur launch_app.bat / launch_app.sh

7 pages accessibles via la sidebar :
  1. 🏠 Tableau de bord   — état du bot, métriques, lancer une recherche
  2. 🔍 Recherche         — mots-clés, villes, paramètres
  3. 📡 Sources           — activer/désactiver, état des clés
  4. 🔑 Clés API          — saisir et sauvegarder les secrets
  5. 📋 Offres            — tableau filtrable, gestion des statuts
  6. 📧 Alertes email     — IMAP, test connexion, lecture manuelle
  7. ⏰ Automatisation    — planifier le lancement quotidien
"""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from bot.config_manager import ConfigManager, SOURCE_META
from bot.database import (
    STATUS_LABELS,
    get_advanced_stats,
    get_all_sources,
    get_offers_filtered,
    get_recent_offers,
    get_stats,
    init_database,
    update_offers_status_batch,
)
from bot.secrets_manager import SECRETS_REGISTRY, SecretsManager
from bot.api_guides import API_GUIDES

# ---------------------------------------------------------------------------
# Configuration Streamlit — doit être la première commande st.*
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="JobBot",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
LOG_RUN_FILE = Path("logs/current_run.log")
LAST_RUN_FILE = Path("data/last_run.json")
STATUS_ORDER = list(STATUS_LABELS.keys())

# ---------------------------------------------------------------------------
# Singletons — instanciés une seule fois par session Streamlit
# ---------------------------------------------------------------------------

@st.cache_resource
def get_cfg() -> ConfigManager:
    return ConfigManager()


@st.cache_resource
def get_sm() -> SecretsManager:
    return SecretsManager()


# ---------------------------------------------------------------------------
# CSS global
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown("""
    <style>
      /* Sidebar plus étroite */
      [data-testid="stSidebar"] { min-width: 220px; max-width: 240px; }
      /* Titres de sections */
      .section-title {
        font-size: 13px; font-weight: 700; letter-spacing: .06em;
        text-transform: uppercase; color: #5f6368; margin: 16px 0 8px;
      }
      /* Badge de statut source */
      .badge {
        display: inline-block; padding: 2px 10px; border-radius: 12px;
        font-size: 12px; font-weight: 600;
      }
      .badge-ok  { background: #e6f4ea; color: #137333; }
      .badge-warn{ background: #fef3cd; color: #856404; }
      .badge-off { background: #f5f5f5; color: #666; }
      /* Masquer index dataframe */
      .stDataFrame td:first-child,
      .stDataFrame th:first-child { display: none; }
    </style>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Bot runner — sous-processus dans un thread
# ---------------------------------------------------------------------------

def _bot_worker(status: dict, log_path: Path) -> None:
    """
    Tourne dans un thread séparé.
    Lance main.py et écrit la sortie dans un fichier log.

    On utilise un thread (et non asyncio) car Streamlit est
    synchrone — on ne peut pas "attendre" dans le thread principal
    sans bloquer l'interface.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    try:
        with open(log_path, "w", encoding="utf-8", buffering=1) as f:
            proc = subprocess.Popen(
                [sys.executable, "main.py"],
                stdout=f,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(Path(__file__).parent),
            )
            proc.wait()
            status["returncode"] = proc.returncode
    except Exception as e:
        status["returncode"] = -1
        try:
            log_path.write_text(
                f"Erreur au lancement du bot : {e}\n", encoding="utf-8"
            )
        except OSError:
            pass
    finally:
        status["running"] = False


def launch_bot() -> None:
    """Lance le bot dans un thread daemon."""
    if st.session_state.get("bot_running"):
        return
    status = {"running": True, "returncode": None}
    st.session_state["bot_status"] = status
    st.session_state["bot_started_at"] = datetime.now().strftime(
        "%d/%m/%Y %H:%M:%S"
    )
    thread = threading.Thread(
        target=_bot_worker,
        args=(status, LOG_RUN_FILE),
        daemon=True,
    )
    thread.start()
    st.session_state["bot_running"] = True


def render_bot_log_box() -> None:
    """Affiche le log de la dernière exécution."""
    if not LOG_RUN_FILE.exists():
        return
    content = LOG_RUN_FILE.read_text(encoding="utf-8").strip()
    if content:
        st.code(content, language=None)


# ---------------------------------------------------------------------------
# Run helpers — progression et résumé post-exécution
# ---------------------------------------------------------------------------

def _read_last_run() -> dict:
    """Lit data/last_run.json écrit par main.py, ou {} si absent."""
    try:
        return json.loads(LAST_RUN_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _render_run_progress(log_content: str, total_sources: int) -> None:
    """Barre de progression + liste des sources déjà traitées."""
    completed = [
        ln.strip() for ln in log_content.splitlines()
        if ln.strip().startswith(("✓ ", "✗ "))
    ]
    done = len(completed)
    st.progress(
        min(done / max(total_sources, 1), 0.99),
        text=f"{done}/{total_sources} sources traitées",
    )
    for line in completed:
        icon = "✅" if line.startswith("✓") else "❌"
        parts = line.split()
        name = parts[1] if len(parts) > 1 else line
        offers = "?"
        for i, p in enumerate(parts):
            if p == "offres" and i > 0:
                offers = parts[i - 1]
                break
        st.caption(f"{icon} **{name}** — {offers} offres")
    if not completed:
        st.caption("🔄 Démarrage en cours…")


def _render_run_summary(result: dict, show_logs: bool) -> None:
    """Résumé structuré après exécution réussie."""
    if not result:
        st.success("✅ Recherche terminée")
        with st.expander("📋 Voir les logs", expanded=show_logs):
            render_bot_log_box()
        return

    dur = result.get("duration", 0)
    new_count = result.get("new_offers", 0)
    total_found = result.get("total_found", 0)
    dupes = max(0, total_found - new_count)

    st.success(
        f"✅ Terminée en **{dur:.0f}s** — "
        f"**{new_count} nouvelles offres** ajoutées"
    )

    sources = result.get("sources", {})
    if sources:
        cols = st.columns(max(len(sources), 1))
        for i, (name, stats) in enumerate(sources.items()):
            with cols[i]:
                ok = stats.get("success", 0)
                no_r = stats.get("no_results", 0)
                err = stats.get("errors", 0)
                offers = stats.get("offers", 0)
                header = f"⚠️ {name}" if err else name
                detail = f"🔍 {offers} offres · ✓ {ok} ok"
                if no_r:
                    detail += f" · ○ {no_r} vide"
                if err:
                    detail += f" · ✗ {err} err"
                st.markdown(f"**{header}**  \n{detail}")

    st.markdown(
        f"**Total :** {total_found} offres brutes → "
        f"**{new_count} nouvelles** · {dupes} déjà connues"
    )
    with st.expander("📋 Logs techniques", expanded=show_logs):
        render_bot_log_box()
        debug = Path("logs/jobbot_debug.log")
        if debug.exists():
            st.caption(f"Logs détaillés : `{debug}`")


def _render_new_offers_preview(result: dict) -> None:
    """Affiche les nouvelles offres ajoutées lors du dernier run."""
    preview = result.get("new_offers_preview", [])
    new_count = result.get("new_offers", 0)
    if not preview:
        if new_count == 0:
            st.info("Aucune nouvelle offre lors de ce run.")
        return

    st.markdown("#### 🆕 Nouvelles offres ajoutées")
    shown = preview[:10]
    for offer in shown:
        title = offer.get("title", "")
        company = offer.get("company", "") or ""
        location = offer.get("location", "") or ""
        source = offer.get("source", "")
        score = offer.get("score", 0)
        url = offer.get("url", "#") or "#"
        meta_parts = [p for p in [company, location, source] if p]
        meta = " · ".join(meta_parts)
        st.markdown(
            f"**{'★' * min(score // 2, 5) or '☆'}** "
            f"[{title}]({url})"
            + (f" — <small style='color:#5f6368'>{meta}</small>" if meta else ""),
            unsafe_allow_html=True,
        )
    if new_count > 10:
        st.caption(f"+ {new_count - 10} autres offres — voir l'onglet Offres")


# ---------------------------------------------------------------------------
# Test rapide d'une source API
# ---------------------------------------------------------------------------

def _test_source_api(
    name: str, sm: "SecretsManager", cfg: "ConfigManager"
) -> tuple[bool, str]:
    """
    Lance une mini-recherche (1 mot-clé, Toulouse) pour tester une source.
    Retourne (ok, message lisible).
    """
    from dotenv import load_dotenv
    load_dotenv()

    status = sm.status_for_source(name)
    if not status["configured"]:
        missing = ", ".join(status["missing"])
        return False, f"Clés manquantes dans .env : {missing}"

    raw = cfg.get_raw()
    raw.setdefault("search", {})["include_remote"] = False

    try:
        if name == "france_travail":
            from bot.sources.france_travail import FranceTravailSource as Cls
        elif name == "adzuna":
            from bot.sources.adzuna import AdzunaSource as Cls
        elif name == "jooble":
            from bot.sources.jooble import JoobleSource as Cls
        elif name == "brave_search":
            from bot.sources.brave_search import BraveSearchSource as Cls
        else:
            return False, "Test non disponible pour cette source"

        src = Cls(raw)
        if not src.is_available():
            return False, "Clés API non reconnues (vérifie .env)"

        offers = src.search(
            ["informatique"],
            [{"name": "Toulouse", "commune_code": "31555"}],
        )
        stats = getattr(src, "stats", {})
        n = len(offers)
        err = stats.get("errors", 0)

        if err and n == 0:
            codes = stats.get("error_codes", "")
            diag = stats.get("diagnosis", "")
            detail = (
                f"{codes} — {diag}" if (codes and diag)
                else codes or diag or "erreur API"
            )
            return False, f"Erreur API : {detail[:120]}"

        if n == 0:
            return True, (
                "API fonctionnelle — 0 offre trouvée "
                "(normal pour un test ponctuel)"
            )
        return True, (
            f"{n} offre(s) trouvée(s) pour « informatique » à Toulouse"
        )
    except Exception as e:
        return False, f"Erreur : {e}"


# ---------------------------------------------------------------------------
# Guides API — helpers pour page_secrets
# ---------------------------------------------------------------------------

def _guide_status_icon(group_key: str, sm: "SecretsManager") -> str:
    """Retourne une icône de statut pour l'en-tête d'expander."""
    guide = API_GUIDES.get(group_key)
    if not guide:
        return ""
    if not guide["needs_key"]:
        return "🆓"
    all_set = (
        all(sm.has(k) for k in guide["env_vars"])
        if guide["env_vars"] else True
    )
    return "✅" if all_set else "⚠️"


def _render_api_guide(group_key: str, sm: "SecretsManager") -> None:
    """
    Affiche le mini-tutoriel d'un service API à l'intérieur d'un expander.
    Appelé au début de chaque section de la page Clés API.
    """
    guide = API_GUIDES.get(group_key)
    if not guide:
        return

    # --- Bandeau de statut ---
    if not guide["needs_key"]:
        st.success(
            "🆓 **Fonctionne sans clé** — active-la directement depuis "
            "la page Sources."
        )
    else:
        env_vars = guide["env_vars"]
        if env_vars:
            missing = [k for k in env_vars if not sm.has(k)]
            if not missing:
                st.success(
                    "✅ **Configurée** — toutes les clés sont présentes."
                )
            else:
                st.warning(
                    f"⚠️ **Clé(s) manquante(s) :** {', '.join(missing)}"
                )

    # --- Description ---
    cols = st.columns([3, 1, 1, 1])
    cols[0].markdown(f"_{guide['purpose']}_")
    cols[1].caption("🎁 Gratuite" if guide["free"] else "💳 Payante")
    cols[2].caption(
        "🔑 Clé requise" if guide["needs_key"] else "🆓 Sans inscription"
    )
    cols[3].caption(
        "⭐ Recommandée" if guide["recommended"] else "➕ Optionnelle"
    )

    # --- Étapes (st.expander interdit dans un expander → <details> HTML) ---
    if guide["steps"] and guide["steps"][0] != "Aucune configuration requise.":
        items = "".join(
            f"<li style='margin:4px 0'>{s}</li>"
            for s in guide["steps"]
        )
        link = ""
        if guide.get("signup_url"):
            url = guide["signup_url"]
            link = (
                f'<p style="margin-top:8px">👉 '
                f'<a href="{url}" target="_blank">'
                f"Créer un compte / obtenir la clé</a></p>"
            )
        st.markdown(
            f"<details><summary>"
            f"<strong>📋 Comment obtenir la clé — étapes</strong>"
            f"</summary><ol style='margin:8px 0 4px 16px'>"
            f"{items}</ol>{link}</details>",
            unsafe_allow_html=True,
        )
    elif guide["steps"]:
        st.caption("ℹ️ Aucune configuration requise — prête à l'emploi.")

    # --- Erreurs fréquentes ---
    if guide.get("common_errors"):
        rows = "".join(
            f"<li style='margin:6px 0'>"
            f"<strong>{e}</strong><br>"
            f"<span style='color:#5f6368;font-size:13px'>{s}</span>"
            f"</li>"
            for e, s in guide["common_errors"]
        )
        st.markdown(
            f"<details><summary>"
            f"<strong>⚠️ Erreurs fréquentes et solutions</strong>"
            f"</summary><ul style='margin:8px 0 4px 16px'>"
            f"{rows}</ul></details>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Sidebar — navigation
# ---------------------------------------------------------------------------

def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## 💼 JobBot")
        st.markdown("---")
        page = st.radio(
            "Navigation",
            [
                "🏠 Tableau de bord",
                "🔍 Recherche",
                "📡 Sources",
                "🔑 Clés API",
                "📋 Offres",
                "📧 Alertes email",
                "⏰ Automatisation",
            ],
            label_visibility="collapsed",
        )
        st.markdown("---")

        # Statut rapide du bot
        is_running = st.session_state.get("bot_running", False)
        status = st.session_state.get("bot_status", {})

        if is_running and status.get("running"):
            st.info("🔄 Bot en cours…")
        elif status.get("returncode") == 0:
            started = st.session_state.get("bot_started_at", "")
            st.success(f"✅ Dernier lancement : {started}")
        elif status.get("returncode") is not None:
            st.error("❌ Dernière exécution en erreur")

    return page


# ===========================================================================
# PAGE 1 — Tableau de bord
# ===========================================================================

def page_dashboard() -> None:
    st.markdown("# 🏠 Tableau de bord")

    cfg = get_cfg()
    db_path = cfg.db_path

    # S'assurer que la base existe
    try:
        init_database(db_path)
    except Exception as e:
        st.error(f"Impossible d'accéder à la base de données : {e}")
        return

    stats = get_advanced_stats(db_path)
    by_status = stats.get("by_status", {})

    # --- Métriques ---
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📦 Offres total", stats.get("total", 0))
    c2.metric("🆕 Nouvelles",    by_status.get("new", 0))
    c3.metric("⭐ Intéressantes",by_status.get("interested", 0))
    c4.metric("📤 Postulées",    by_status.get("applied", 0))
    c5.metric("❌ Refusées",     by_status.get("rejected", 0))

    st.markdown("---")

    # --- Lancer le bot ---
    col_btn, col_info = st.columns([2, 3])
    with col_btn:
        is_running = (
            st.session_state.get("bot_running", False)
            and st.session_state.get("bot_status", {}).get("running", False)
        )
        if is_running:
            st.button("🔄 Recherche en cours…", disabled=True,
                      use_container_width=True)
        else:
            if st.button("🚀 Lancer une recherche maintenant",
                         type="primary", use_container_width=True):
                launch_bot()
                st.rerun()

    with col_info:
        sources_on = [
            s for s in SOURCE_META
            if cfg.is_source_enabled(s)
        ]
        st.caption(
            f"Sources actives : {', '.join(sources_on) or 'aucune'}"
        )

    # --- Auto-refresh pendant l'exécution ---
    status = st.session_state.get("bot_status", {})
    ui_cfg = cfg.get_raw().get("ui", {})
    show_logs = ui_cfg.get("show_logs_by_default", False)

    if status.get("running"):
        n_sources = sum(
            1 for s in SOURCE_META if cfg.is_source_enabled(s)
        )
        log_content = (
            LOG_RUN_FILE.read_text(encoding="utf-8")
            if LOG_RUN_FILE.exists() else ""
        )
        _render_run_progress(log_content, n_sources)
        time.sleep(2)
        st.rerun()
    elif status.get("returncode") is not None:
        rc = status["returncode"]
        if rc == 0:
            last_run = _read_last_run()
            _render_run_summary(last_run, show_logs)
            if last_run:
                _render_new_offers_preview(last_run)
        else:
            st.error(f"❌ La recherche a échoué (code {rc})")
            with st.expander("📋 Voir les logs", expanded=True):
                render_bot_log_box()
        st.session_state["bot_running"] = False

    st.markdown("---")

    # --- Timeline ---
    timeline = stats.get("timeline", [])
    if timeline:
        st.markdown("##### 📅 Offres trouvées ces 14 derniers jours")
        df_t = pd.DataFrame(timeline)
        df_t["day"] = pd.to_datetime(df_t["day"])
        st.line_chart(df_t.set_index("day"), use_container_width=True)

    # --- Top offres ---
    top = get_offers_filtered(db_path, min_score=8, limit=5)
    if top:
        st.markdown("##### 🏆 Meilleures offres récentes")
        for row in top:
            score = row.get("score", 0)
            title = row.get("title", "")
            company = row.get("company", "") or ""
            url = row.get("url", "#")
            src = row.get("source", "")
            st.markdown(
                f"**{'★' * min(score // 2, 5)}** "
                f"[{title}]({url}) — {company} "
                f"<small style='color:#5f6368'>({src})</small>",
                unsafe_allow_html=True,
            )


# ===========================================================================
# PAGE 2 — Configuration de recherche
# ===========================================================================

def page_search_config() -> None:
    st.markdown("# 🔍 Configuration de la recherche")
    st.caption(
        "Ces paramètres sont sauvegardés dans `config.yaml`. "
        "Le bot les utilisera au prochain lancement."
    )

    cfg = get_cfg()

    with st.form("search_config_form"):
        st.markdown("#### Mots-clés")
        keywords_text = st.text_area(
            "Un mot-clé par ligne",
            value="\n".join(cfg.keywords),
            height=200,
            help="Le bot cherchera chaque mot-clé sur toutes les sources actives.",
        )

        st.markdown("#### Villes")
        st.caption(
            "Format : `Nom de la ville | Code INSEE` — "
            "trouve les codes sur [geo.api.gouv.fr](https://geo.api.gouv.fr/communes)"
        )

        # Construire le texte des localisations
        locs_text = "\n".join(
            f"{loc['name']} | {loc.get('commune_code', '')}"
            for loc in cfg.locations
        )
        locations_text = st.text_area(
            "Une ville par ligne (Nom | Code INSEE)",
            value=locs_text,
            height=120,
            help="Ex:\nToulouse | 31555\nMontauban | 82121\nCaussade | 82033",
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            distance_km = st.number_input(
                "Rayon de recherche (km)",
                min_value=5, max_value=200, value=cfg.distance_km, step=5,
            )
        with col2:
            days_published = st.number_input(
                "Offres publiées depuis (jours)",
                min_value=1, max_value=30, value=cfg.days_published,
            )
        with col3:
            min_score = st.number_input(
                "Score minimum",
                min_value=0, max_value=15, value=cfg.min_score,
            )

        include_remote = st.checkbox(
            "Inclure les offres en télétravail",
            value=cfg.include_remote,
        )

        contract_options = ["CDI", "CDD", "ALT", "MIS", "SAI"]
        contract_types = st.multiselect(
            "Types de contrats",
            options=contract_options,
            default=cfg.contract_types,
        )

        st.markdown("#### Email de résumé quotidien")
        col_r, col_s = st.columns(2)
        with col_r:
            email_recipient = st.text_input(
                "Adresse de réception",
                value=cfg.email_config.get("recipient", ""),
                placeholder="toi@gmail.com",
            )
        with col_s:
            max_offers = st.number_input(
                "Offres max dans l'email",
                min_value=5, max_value=100,
                value=cfg.email_config.get("max_offers_in_email", 25),
            )

        submitted = st.form_submit_button(
            "💾 Sauvegarder la configuration", type="primary"
        )

    if submitted:
        # Mots-clés
        keywords = [
            k.strip()
            for k in keywords_text.splitlines()
            if k.strip()
        ]

        # Localisations
        locations = []
        for line in locations_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                name, _, code = line.partition("|")
                locations.append({
                    "name": name.strip(),
                    "commune_code": code.strip(),
                })
            else:
                locations.append({"name": line, "commune_code": ""})

        # Sauvegarder
        cfg.set_keywords(keywords)
        cfg.set_locations(locations)
        cfg.set_distance_km(distance_km)
        cfg.set_days_published(days_published)
        cfg.set_include_remote(include_remote)
        cfg.set_contract_types(contract_types)
        cfg.set_min_score(min_score)
        cfg.set_email_config(
            recipient=email_recipient,
            max_offers=max_offers,
        )

        # Recharger le ConfigManager depuis le fichier
        get_cfg.clear()

        st.success(
            f"✅ Configuration sauvegardée — "
            f"{len(keywords)} mots-clés, {len(locations)} ville(s)"
        )


# ===========================================================================
# PAGE 3 — Sources
# ===========================================================================

def page_sources() -> None:
    st.markdown("# 📡 Sources d'offres")
    st.caption(
        "Active ou désactive chaque source. "
        "Une source ne peut fonctionner que si ses clés API sont configurées "
        "(page Clés API)."
    )

    cfg = get_cfg()
    sm = get_sm()
    last_run = _read_last_run()
    last_run_sources = set(last_run.get("sources", {}).keys())

    # ── Tableau récapitulatif ──────────────────────────────────────────
    rows = []
    for name, meta in SOURCE_META.items():
        enabled = cfg.is_source_enabled(name)
        secret_status = sm.status_for_source(name)
        requires = meta.get("requires", [])
        configured = not requires or secret_status["configured"]
        in_last_run = name in last_run_sources
        last_stats = last_run.get("sources", {}).get(name, {})

        clés_col = "—" if not requires else (
            "✅" if configured
            else "❌ " + ", ".join(secret_status["missing"])
        )

        if not enabled:
            diag = "Désactivée"
        elif not configured:
            diag = "Manque : " + ", ".join(secret_status["missing"])
        elif in_last_run:
            diag = f"Active — {last_stats.get('offers', 0)} offres"
        else:
            diag = "Prête (pas encore utilisée ce run)"

        rows.append({
            "Source": f"{meta['emoji']} {meta['label']}",
            "Act.": "✅" if enabled else "⏸️",
            "Clés API": clés_col,
            "Dernier run": (
                "✓" if in_last_run
                else ("✗" if last_run_sources else "—")
            ),
            "Diagnostic": diag,
        })
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, use_container_width=True
    )
    st.markdown("---")
    # ── Cartes interactives ───────────────────────────────────────────

    for name, meta in SOURCE_META.items():
        with st.container():
            col_info, col_status, col_max, col_toggle = st.columns(
                [3, 2, 2, 1]
            )

            # Statut
            enabled = cfg.is_source_enabled(name)
            secret_status = sm.status_for_source(name)

            if not meta["requires"]:
                status_badge = "✅ Gratuite — sans clé"
                status_color = "badge-ok"
            elif secret_status["configured"]:
                status_badge = "✅ Configurée"
                status_color = "badge-ok"
            else:
                status_badge = "⚠️ Clé(s) manquante(s)"
                status_color = "badge-warn"

            if not enabled:
                status_color = "badge-off"

            with col_info:
                st.markdown(
                    f"**{meta['emoji']} {meta['label']}**  \n"
                    f"<small style='color:#5f6368'>{meta['description']}</small>",
                    unsafe_allow_html=True,
                )
                if meta["signup_url"]:
                    st.caption(
                        f"[Inscription]({meta['signup_url']}) — {meta['quota']}"
                    )
                elif meta["free"]:
                    st.caption(f"Gratuite — {meta['quota']}")

            with col_status:
                st.markdown(
                    f'<span class="badge {status_color}">'
                    f'{status_badge}</span>',
                    unsafe_allow_html=True,
                )
                if not meta["requires"]:
                    pass
                elif not secret_status["configured"]:
                    missing = secret_status["missing"]
                    st.caption(f"Manque : {', '.join(missing)}")
                # Indicateur dernier run
                if enabled and last_run_sources:
                    if name in last_run_sources:
                        st.caption("✓ active au dernier run")
                    else:
                        st.caption("✗ ignorée au dernier run")

            with col_max:
                src_cfg = cfg.get_source_config(name)
                current_max = src_cfg.get("max_results_per_keyword", 25)
                new_max = st.number_input(
                    "Max résultats",
                    min_value=5, max_value=100,
                    value=current_max,
                    key=f"max_{name}",
                    label_visibility="collapsed",
                )
                if new_max != current_max:
                    cfg.set_source_max_results(name, new_max)

            with col_toggle:
                new_enabled = st.toggle(
                    "Activer",
                    value=enabled,
                    key=f"toggle_{name}",
                    label_visibility="collapsed",
                )
                if new_enabled != enabled:
                    cfg.set_source_enabled(name, new_enabled)
                    get_cfg.clear()
                    st.rerun()

        st.divider()

    # Bouton "Tester les sources"
    if st.button("🔬 Tester les sources configurées", type="secondary"):
        results = []
        for name, meta in SOURCE_META.items():
            if not cfg.is_source_enabled(name):
                results.append((name, "⏸️", "Désactivée"))
                continue
            status_info = sm.status_for_source(name)
            if not meta["requires"] or status_info["configured"]:
                results.append((name, "✅", "Prête"))
            else:
                missing = ", ".join(status_info["missing"])
                results.append((name, "❌", f"Clés manquantes : {missing}"))

        for name, icon, msg in results:
            meta = SOURCE_META.get(name, {})
            label = meta.get("label", name)
            if icon == "✅":
                st.success(f"{icon} **{label}** — {msg}")
            elif icon == "⏸️":
                st.info(f"{icon} **{label}** — {msg}")
            else:
                st.error(f"{icon} **{label}** — {msg}")


# ===========================================================================
# PAGE 4 — Clés API et secrets
# ===========================================================================

def page_secrets() -> None:
    st.markdown("# 🔑 Clés API et secrets")
    st.warning(
        "🔒 **Sécurité** — Ces clés sont stockées dans `.env` sur ton disque local. "
        "Elles ne sont jamais envoyées à Internet depuis cette interface. "
        "Ne les communique jamais à personne."
    )

    sm = get_sm()

    # Vérification .gitignore
    if sm.ensure_gitignore():
        st.info("✅ `.env` ajouté à `.gitignore` — tes secrets sont protégés.")

    # Regrouper les secrets par source
    groups: dict[str, list[str]] = {}
    for key, meta in SECRETS_REGISTRY.items():
        groups.setdefault(meta["source"], []).append(key)

    group_labels = {
        "france_travail": "🇫🇷 France Travail",
        "adzuna":         "🔍 Adzuna",
        "jooble":         "🌐 Jooble",
        "careerjet":      "📋 Careerjet",
        "brave_search":   "🦁 Brave Search",
        "email_smtp":     "📤 Email SMTP (rapport quotidien)",
        "email_alerts":   "📧 IMAP (alertes email)",
    }

    # Formulaire par groupe
    for group_key, keys in groups.items():
        label = group_labels.get(group_key, group_key)
        icon = _guide_status_icon(group_key, sm)
        with st.expander(f"{icon} **{label}**", expanded=False):

            # Mini-tutoriel intégré
            _render_api_guide(group_key, sm)
            st.divider()

            # Champs de saisie des secrets
            new_values: dict[str, str] = {}
            has_changes = False

            for key in keys:
                meta = SECRETS_REGISTRY[key]
                already_set = sm.has(key)
                current_masked = sm.mask(key) if already_set else ""

                col_label, col_input, col_del = st.columns([2, 4, 1])
                with col_label:
                    st.markdown(
                        f"**{meta['label']}**  \n"
                        f"<small style='color:#5f6368'>"
                        f"{meta['description']}</small>",
                        unsafe_allow_html=True,
                    )
                    if already_set:
                        st.caption(f"Actuel : `{current_masked}`")

                with col_input:
                    placeholder = (
                        "Laisser vide pour conserver l'existant"
                        if already_set else "Saisir la valeur..."
                    )
                    new_val = st.text_input(
                        key,
                        value="",
                        placeholder=placeholder,
                        type="password" if meta["is_password"] else "default",
                        key=f"input_{key}",
                        label_visibility="collapsed",
                    )
                    if new_val.strip():
                        new_values[key] = new_val.strip()
                        has_changes = True

                with col_del:
                    if already_set:
                        if st.button(
                            "🗑️", key=f"del_{key}",
                            help=f"Supprimer {key}",
                        ):
                            if st.session_state.get(
                                f"confirm_del_{key}", False
                            ):
                                sm.delete(key)
                                st.success(f"✅ {key} supprimé")
                                st.rerun()
                            else:
                                st.session_state[
                                    f"confirm_del_{key}"
                                ] = True
                                st.warning(
                                    "Clique à nouveau pour confirmer "
                                    "la suppression"
                                )

            if has_changes:
                if st.button(
                    f"💾 Sauvegarder {label}",
                    key=f"save_{group_key}",
                    type="primary",
                ):
                    sm.set_many(new_values)
                    st.success(
                        f"✅ {len(new_values)} secret(s) sauvegardés. "
                        "Les valeurs sont maintenant masquées."
                    )
                    st.rerun()

            # Bouton de test contextuel
            _API_TEST_SOURCES = {
                "france_travail": "🇫🇷 Tester France Travail",
                "adzuna":         "🔍 Tester Adzuna",
                "jooble":         "🌐 Tester Jooble",
                "brave_search":   "🦁 Tester Brave Search",
            }
            if group_key in _API_TEST_SOURCES:
                st.markdown("")
                if st.button(
                    _API_TEST_SOURCES[group_key],
                    key=f"test_{group_key}_btn",
                ):
                    label = group_labels.get(group_key, group_key)
                    with st.spinner(
                        f"Test {label} en cours "
                        f"(« informatique » à Toulouse)…"
                    ):
                        ok, msg = _test_source_api(
                            group_key, sm, get_cfg()
                        )
                    st.success(msg) if ok else st.error(msg)

            elif group_key == "email_smtp":
                st.markdown("")
                if st.button(
                    "📤 Tester l'envoi email (SMTP)",
                    key="test_smtp_btn",
                ):
                    with st.spinner("Connexion SMTP en cours…"):
                        ok, msg = sm.test_smtp()
                    st.success(msg) if ok else st.error(msg)

            elif group_key == "email_alerts":
                st.markdown("")
                if st.button(
                    "📥 Tester la connexion IMAP",
                    key="test_imap_btn",
                ):
                    with st.spinner("Connexion IMAP en cours…"):
                        ok, msg = sm.test_imap()
                    st.success(msg) if ok else st.error(msg)

    # ------------------------------------------------------------------
    # Sources sans inscription requise (The Muse)
    # Absentes de SECRETS_REGISTRY car elles ne nécessitent aucune clé.
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 🆓 Sources sans clé API")
    st.caption(
        "Ces sources fonctionnent immédiatement, sans inscription. "
        "Active-les depuis la page Sources."
    )

    muse_meta = SOURCE_META.get("themuse", {})
    muse_enabled = get_cfg().is_source_enabled("themuse")
    muse_status = "✅ Activée" if muse_enabled else "⏸️ Désactivée"
    with st.expander(
        f"🆓 **{muse_meta.get('label', 'The Muse')}** — {muse_status}",
        expanded=False,
    ):
        _render_api_guide("themuse", sm)


# ===========================================================================
# PAGE 5 — Offres
# ===========================================================================

def page_offers() -> None:
    st.markdown("# 📋 Offres d'emploi")

    cfg = get_cfg()
    db_path = cfg.db_path

    try:
        init_database(db_path)
    except Exception as e:
        st.error(f"Base de données inaccessible : {e}")
        return

    # --- Filtre rapide "aujourd'hui" ---
    today_only = st.session_state.get("offers_today_filter", False)
    col_today, _ = st.columns([2, 5])
    with col_today:
        if st.button(
            "📅 Voir les offres ajoutées aujourd'hui",
            type="secondary" if not today_only else "primary",
        ):
            st.session_state["offers_today_filter"] = not today_only
            st.rerun()

    # --- Filtres ---
    with st.expander("🔽 Filtres", expanded=True):
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        with fc1:
            search_kw = st.text_input("🔍 Mot-clé", placeholder="SOC, Linux…")
        with fc2:
            location_kw = st.text_input("📍 Ville", placeholder="Toulouse")
        with fc3:
            min_score = st.slider("⭐ Score min", 0, 15, 2)
        with fc4:
            all_sources = get_all_sources(db_path)
            selected_sources = st.multiselect("📡 Sources", all_sources)
        with fc5:
            selected_statuses = st.multiselect(
                "📋 Statuts",
                STATUS_ORDER,
                format_func=lambda s: STATUS_LABELS.get(s, s),
            )

    rows = get_offers_filtered(
        db_path,
        sources=selected_sources or None,
        statuses=selected_statuses or None,
        min_score=min_score,
        location_kw=location_kw,
        search_kw=search_kw,
        limit=500,
    )

    if today_only:
        today_str = datetime.now().strftime("%Y-%m-%d")
        rows = [
            r for r in rows
            if (r.get("found_at") or "").startswith(today_str)
        ]

    if not rows:
        msg = (
            "Aucune offre ajoutée aujourd'hui."
            if today_only else
            "Aucune offre pour ces filtres. "
            "Lance le bot depuis le tableau de bord."
        )
        st.info(msg)
        return

    label = "aujourd'hui" if today_only else "offre(s)"
    st.caption(f"{len(rows)} {label}")

    df = pd.DataFrame(rows)
    display_cols = [
        "id", "score", "title", "company", "location",
        "contract", "source", "status", "url",
    ]
    df_disp = df[[c for c in display_cols if c in df.columns]].copy()

    # Sauvegarder les statuts originaux AVANT l'éditeur
    original_statuses = df_disp["status"].copy() if "status" in df_disp.columns else None

    df_disp = df_disp.rename(columns={
        "score": "⭐", "title": "Titre", "company": "Société",
        "location": "Lieu", "contract": "Contrat",
        "source": "Source", "status": "Statut", "url": "Lien",
    })

    edited = st.data_editor(
        df_disp,
        key="offers_editor",
        use_container_width=True,
        hide_index=True,
        column_config={
            "id":      None,
            "⭐":      st.column_config.NumberColumn(
                           format="%d", width="small", disabled=True),
            "Titre":   st.column_config.TextColumn(width="large", disabled=True),
            "Société": st.column_config.TextColumn(width="medium", disabled=True),
            "Lieu":    st.column_config.TextColumn(width="small", disabled=True),
            "Contrat": st.column_config.TextColumn(width="small", disabled=True),
            "Source":  st.column_config.TextColumn(width="small", disabled=True),
            "Statut":  st.column_config.SelectboxColumn(
                           options=STATUS_ORDER, required=True, width="medium"),
            "Lien":    st.column_config.LinkColumn(
                           display_text="Ouvrir →", width="small", disabled=True),
        },
        num_rows="fixed",
    )

    col_save, _ = st.columns([2, 5])
    with col_save:
        if st.button("💾 Sauvegarder les statuts", type="primary",
                     use_container_width=True):
            if original_statuses is not None:
                changed = edited[edited["Statut"] != original_statuses.values]
                if changed.empty:
                    st.info("Aucun changement.")
                else:
                    updates = {
                        df_disp.loc[i, "id"]: changed.loc[i, "Statut"]
                        for i in changed.index
                        if "id" in df_disp.columns
                    }
                    from bot.database import update_offers_status_batch
                    n = update_offers_status_batch(db_path, updates)
                    st.success(f"✅ {n} statut(s) mis à jour")
                    st.rerun()

    # Légende
    with st.expander("ℹ️ Légende des statuts"):
        cols = st.columns(4)
        for i, (k, label) in enumerate(STATUS_LABELS.items()):
            cols[i % 4].markdown(f"**{label}**")


# ===========================================================================
# PAGE 6 — Alertes email
# ===========================================================================

def page_email_alerts() -> None:
    st.markdown("# 📧 Alertes email")
    st.markdown(
        "Ce module lit les emails d'alerte emploi reçus dans ta boîte "
        "(LinkedIn, Indeed, HelloWork, WTTJ, APEC…) et en extrait "
        "les offres automatiquement — sans scraping, sans risque."
    )

    cfg = get_cfg()
    sm = get_sm()

    # --- Configuration IMAP ---
    with st.form("imap_form"):
        st.markdown("#### Connexion IMAP")
        col1, col2 = st.columns(2)
        with col1:
            imap_email = st.text_input(
                "Adresse email",
                value=sm.get("IMAP_EMAIL") or "",
                placeholder="toi@gmail.com",
                type="default",
            )
        with col2:
            imap_password = st.text_input(
                "Mot de passe d'application",
                placeholder="(laisser vide pour conserver)",
                type="password",
            )
        col3, col4 = st.columns(2)
        with col3:
            imap_host = st.text_input(
                "Serveur IMAP (optionnel)",
                value=sm.get("IMAP_HOST") or "",
                placeholder="Auto-détecté pour Gmail/Outlook/Orange…",
            )
        with col4:
            days_back = st.number_input(
                "Relire les emails des N derniers jours",
                min_value=1, max_value=30,
                value=cfg.get_source_config("email_alerts").get(
                    "days_back", 2
                ),
            )
        mark_as_read = st.checkbox(
            "Marquer les emails traités comme 'lus'",
            value=cfg.get_source_config("email_alerts").get(
                "mark_as_read", False
            ),
        )
        enabled = st.checkbox(
            "✅ Activer les alertes email",
            value=cfg.is_source_enabled("email_alerts"),
        )

        if st.form_submit_button("💾 Sauvegarder", type="primary"):
            secrets: dict[str, str] = {}
            if imap_email.strip():
                secrets["IMAP_EMAIL"] = imap_email.strip()
            if imap_password.strip():
                secrets["IMAP_PASSWORD"] = imap_password.strip()
            if imap_host.strip():
                secrets["IMAP_HOST"] = imap_host.strip()
            if secrets:
                sm.set_many(secrets)

            cfg.set_email_alerts_config(
                days_back=days_back,
                mark_as_read=mark_as_read,
                mailbox="INBOX",
            )
            cfg.set_source_enabled("email_alerts", enabled)
            get_cfg.clear()
            st.success("✅ Configuration sauvegardée")

    # --- Test connexion ---
    col_test, col_read = st.columns(2)

    with col_test:
        if st.button("🔌 Tester la connexion IMAP"):
            with st.spinner("Test en cours…"):
                ok, msg = sm.test_imap()
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    with col_read:
        if st.button("📥 Lire les alertes maintenant"):
            if not sm.has("IMAP_EMAIL") or not sm.has("IMAP_PASSWORD"):
                st.error("Configure d'abord l'adresse email et le mot de passe.")
            else:
                with st.spinner("Lecture des alertes email…"):
                    try:
                        from dotenv import load_dotenv
                        load_dotenv()
                        from bot.sources.email_alerts import EmailAlertsSource
                        from bot.database import save_offers, init_database
                        init_database(cfg.db_path)
                        raw_cfg = cfg.get_raw()
                        raw_cfg["sources"]["email_alerts"]["enabled"] = True
                        source = EmailAlertsSource(raw_cfg)
                        offers = source.search(cfg.keywords, cfg.locations)
                        new_count, _ = save_offers(cfg.db_path, offers)
                        st.success(
                            f"✅ {len(offers)} offre(s) extraite(s) — "
                            f"{new_count} nouvelle(s) en base"
                        )
                    except Exception as e:
                        st.error(f"Erreur : {e}")

    st.markdown("---")
    st.markdown("""
### Comment configurer les alertes sur chaque site

1. **LinkedIn** — [linkedin.com/jobs](https://linkedin.com/jobs) → lance une recherche → "Créer une alerte"
2. **Indeed** — [fr.indeed.com](https://fr.indeed.com) → "Créer une alerte emploi"
3. **HelloWork** — [hellowork.com](https://hellowork.com) → "Créer une alerte"
4. **Welcome to the Jungle** — [welcometothejungle.com](https://welcometothejungle.com) → "Mes alertes"
5. **APEC** — [apec.fr](https://apec.fr) → "Créer une alerte offre"

Ces sites enverront leurs offres à ton email.
Le bot les lira automatiquement à chaque lancement.
""")


# ===========================================================================
# PAGE 7 — Automatisation
# ===========================================================================

def page_automation() -> None:
    st.markdown("# ⏰ Automatisation")
    st.markdown(
        "Planifie le lancement automatique du bot chaque matin. "
        "Il cherchera les offres et t'enverra le résumé par email."
    )

    project_dir = str(Path(__file__).parent.resolve())
    python_exec = sys.executable

    col1, col2 = st.columns(2)
    with col1:
        hour = st.number_input("Heure", min_value=0, max_value=23, value=7)
    with col2:
        minute = st.number_input("Minute", min_value=0, max_value=59,
                                 value=30, step=5)

    time_str = f"{int(hour):02d}:{int(minute):02d}"
    st.info(f"⏰ Le bot sera lancé chaque jour à **{time_str}**")

    st.markdown("---")
    tab_win, tab_linux = st.tabs(["🪟 Windows", "🐧 Linux / Mac"])

    # --- Windows ---
    with tab_win:
        task_cmd = (
            f'schtasks /Create /F /TN "JobBot" '
            f'/TR "\\"{python_exec}\\" \\"{project_dir}\\main.py\\"" '
            f'/SC DAILY /ST {time_str}'
        )
        st.code(task_cmd, language="batch")

        if st.button("⚙️ Installer la tâche planifiée (Windows)",
                     key="win_schedule"):
            try:
                result = subprocess.run(
                    [
                        "schtasks", "/Create", "/F",
                        "/TN", "JobBot",
                        "/TR", f'"{python_exec}" "{project_dir}\\main.py"',
                        "/SC", "DAILY",
                        "/ST", time_str,
                    ],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    st.success(
                        f"✅ Tâche planifiée créée — "
                        f"le bot tournera chaque jour à {time_str}"
                    )
                else:
                    st.error(
                        f"Erreur : {result.stderr or result.stdout}\n"
                        "→ Lance ce script en tant qu'administrateur"
                    )
            except FileNotFoundError:
                st.error(
                    "Commande `schtasks` introuvable — "
                    "tu n'es pas sur Windows."
                )

        st.caption(
            "Pour voir la tâche : Planificateur de tâches → "
            "Bibliothèque du Planificateur → JobBot"
        )
        st.caption(
            "Pour supprimer : "
            "`schtasks /Delete /TN \"JobBot\" /F`"
        )

    # --- Linux / Mac ---
    with tab_linux:
        cron_line = (
            f"{int(minute)} {int(hour)} * * * "
            f"cd \"{project_dir}\" && "
            f"\"{python_exec}\" main.py >> logs/cron.log 2>&1"
        )
        st.code(cron_line, language="bash")

        if st.button("⚙️ Installer le cron automatiquement",
                     key="linux_schedule"):
            try:
                # Lire le crontab actuel
                current = subprocess.run(
                    ["crontab", "-l"],
                    capture_output=True, text=True,
                )
                existing = current.stdout if current.returncode == 0 else ""

                if "JobBot" in existing or cron_line in existing:
                    st.warning("Une entrée JobBot existe déjà dans cron.")
                else:
                    new_cron = (
                        existing.rstrip() + "\n"
                        + f"# JobBot — lancé automatiquement\n"
                        + cron_line + "\n"
                    )
                    proc = subprocess.run(
                        ["crontab", "-"],
                        input=new_cron, text=True,
                        capture_output=True,
                    )
                    if proc.returncode == 0:
                        st.success(
                            f"✅ Cron installé — "
                            f"le bot tournera chaque jour à {time_str}"
                        )
                    else:
                        st.error(f"Erreur cron : {proc.stderr}")

            except FileNotFoundError:
                st.error(
                    "Commande `crontab` introuvable. "
                    "Ajoute la ligne manuellement avec `crontab -e`."
                )

        st.caption(
            "Pour voir tes crons : `crontab -l`  \n"
            "Pour éditer : `crontab -e`  \n"
            "Pour supprimer : retire la ligne contenant 'JobBot'"
        )

    st.markdown("---")

    # --- État de l'automatisation ---
    st.markdown("### État actuel")
    col_check_win, col_check_lin = st.columns(2)

    with col_check_win:
        if st.button("🔍 Vérifier la tâche Windows"):
            try:
                result = subprocess.run(
                    ["schtasks", "/Query", "/TN", "JobBot", "/FO", "LIST"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    st.success("✅ Tâche 'JobBot' active sur Windows")
                    st.code(result.stdout, language=None)
                else:
                    st.info("Aucune tâche 'JobBot' trouvée")
            except FileNotFoundError:
                st.info("Windows non détecté")

    with col_check_lin:
        if st.button("🔍 Vérifier le cron"):
            try:
                result = subprocess.run(
                    ["crontab", "-l"],
                    capture_output=True, text=True,
                )
                if result.returncode == 0 and "JobBot" in result.stdout:
                    st.success("✅ Cron 'JobBot' actif")
                    lines = [
                        l for l in result.stdout.splitlines()
                        if "JobBot" in l or l.strip().endswith("main.py")
                    ]
                    st.code("\n".join(lines), language="bash")
                else:
                    st.info("Aucune entrée JobBot dans cron")
            except FileNotFoundError:
                st.info("crontab non disponible sur ce système")


# ===========================================================================
# Point d'entrée principal
# ===========================================================================

def main() -> None:
    _inject_css()

    # Initialiser les variables de session si nécessaire
    for key, default in [
        ("bot_running", False),
        ("bot_status", {}),
        ("bot_started_at", ""),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Détecter si le bot a fini depuis le dernier rerun
    status = st.session_state.get("bot_status", {})
    if (
        st.session_state.get("bot_running")
        and not status.get("running", True)
    ):
        st.session_state["bot_running"] = False

    page = render_sidebar()

    if page == "🏠 Tableau de bord":
        page_dashboard()
    elif page == "🔍 Recherche":
        page_search_config()
    elif page == "📡 Sources":
        page_sources()
    elif page == "🔑 Clés API":
        page_secrets()
    elif page == "📋 Offres":
        page_offers()
    elif page == "📧 Alertes email":
        page_email_alerts()
    elif page == "⏰ Automatisation":
        page_automation()


if __name__ == "__main__":
    main()
