"""
Générateur de rapport quotidien.

V2 : ajoute un résumé des sources en haut du mail.
     Groupe visuellement les offres par source.
"""

from datetime import date
from bot.models import JobOffer

COLOR_PRIMARY = "#1a73e8"
COLOR_BG = "#f8f9fa"
COLOR_CARD = "#ffffff"
COLOR_HIGH = "#137333"
COLOR_MED = "#e37400"
COLOR_LOW = "#c5221f"
COLOR_TEXT = "#202124"
COLOR_MUTED = "#5f6368"

# Couleur et emoji par source
SOURCE_STYLES: dict[str, tuple[str, str]] = {
    "france_travail": ("#1a73e8", "🇫🇷"),
    "adzuna": ("#e67e22", "🔍"),
    "jooble": ("#8e44ad", "🌐"),
    "careerjet": ("#16a085", "📋"),
    "themuse": ("#c0392b", "✨"),
    "brave_search": ("#2980b9", "🦁"),
    "email_alerts": ("#7f8c8d", "📧"),
}


def score_to_stars(score: int) -> str:
    filled = min(max(score // 2, 0), 5)
    return "★" * filled + "☆" * (5 - filled)


def score_to_color(score: int) -> str:
    if score >= 8:
        return COLOR_HIGH
    if score >= 5:
        return COLOR_MED
    return COLOR_LOW


def source_label(source: str) -> tuple[str, str]:
    """Retourne (couleur, emoji) pour une source."""
    # brave_search:apec.fr → on prend juste la partie avant ':'
    base = source.split(":")[0]
    return SOURCE_STYLES.get(base, ("#5f6368", "📌"))


def group_by_source(offers: list) -> dict[str, list]:
    """Groupe les offres par source pour le résumé."""
    groups: dict[str, list] = {}
    for offer in offers:
        base_src = (offer.get("source") or "inconnu").split(":")[0]
        groups.setdefault(base_src, []).append(offer)
    return groups


def generate_html_report(
    offers: list, stats: dict, config: dict, source_counts: dict = None
) -> str:
    """
    Génère le corps HTML de l'email.

    V2 : section résumé des sources + badge coloré sur chaque offre.
    """
    today = date.today().strftime("%d %B %Y")
    nb = len(offers)
    max_offers = config.get("email", {}).get("max_offers_in_email", 25)
    to_show = offers[:max_offers]
    source_counts = source_counts or {}

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:{COLOR_BG};
             font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"
       style="background:{COLOR_BG};padding:20px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0"
       style="max-width:640px;width:100%;">

  <!-- HEADER -->
  <tr>
    <td style="background:{COLOR_PRIMARY};padding:24px 28px;
               border-radius:8px 8px 0 0;">
      <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">
        JobBot &mdash; Rapport quotidien
      </h1>
      <p style="margin:6px 0 0;color:#c6dafc;font-size:14px;">{today}</p>
    </td>
  </tr>

  <!-- STATS GLOBALES -->
  <tr>
    <td style="background:{COLOR_PRIMARY};padding:0 28px 20px;">
      <table width="100%"><tr>
        <td style="color:#fff;font-size:30px;font-weight:700;">{nb}</td>
        <td style="color:#fff;font-size:30px;font-weight:700;">
          {stats.get('total', 0)}</td>
        <td style="color:#fff;font-size:30px;font-weight:700;">
          {stats.get('applied', 0)}</td>
      </tr><tr>
        <td style="color:#c6dafc;font-size:12px;">nouvelles offres</td>
        <td style="color:#c6dafc;font-size:12px;">total en base</td>
        <td style="color:#c6dafc;font-size:12px;">candidatures</td>
      </tr></table>
    </td>
  </tr>
"""

    # --- Résumé des sources ---
    if source_counts:
        html += f"""
  <tr>
    <td style="background:#e8f0fe;padding:12px 28px;
               border-bottom:2px solid {COLOR_PRIMARY};">
      <p style="margin:0 0 8px;color:{COLOR_PRIMARY};
                font-size:12px;font-weight:700;
                letter-spacing:.05em;text-transform:uppercase;">
        Sources interrogées ce matin
      </p>
      <table width="100%"><tr>
"""
        for src, count in sorted(
            source_counts.items(), key=lambda x: x[1], reverse=True
        ):
            color, emoji = source_label(src)
            html += f"""
        <td style="text-align:center;padding:4px 8px;">
          <div style="color:{color};font-size:18px;font-weight:700;">
            {emoji} {count}
          </div>
          <div style="color:{COLOR_MUTED};font-size:10px;">{src}</div>
        </td>"""
        html += "</tr></table></td></tr>"

    # --- Corps ---
    html += f"""
  <tr>
    <td style="background:{COLOR_CARD};padding:20px 28px;
               border-radius:0 0 8px 8px;">
"""
    if not to_show:
        html += """
      <p style="color:#5f6368;text-align:center;padding:40px 0;">
        Aucune nouvelle offre aujourd'hui.
      </p>"""
    else:
        for i, offer in enumerate(to_show):
            # offer peut être un dict (depuis DB) ou un JobOffer
            if isinstance(offer, dict):
                title = offer.get("title", "")
                company = offer.get("company") or ""
                location = offer.get("location") or ""
                contract = offer.get("contract") or "Non précisé"
                salary = offer.get("salary") or "Non précisé"
                description = (offer.get("description") or "")[:280]
                url = offer.get("url", "#")
                score = offer.get("score", 0)
                src = offer.get("source", "")
            else:
                title = offer.title or ""
                company = offer.company or ""
                location = offer.location or ""
                contract = offer.contract or "Non précisé"
                salary = offer.salary or "Non précisé"
                description = (offer.description or "")[:280]
                url = offer.url
                score = offer.score
                src = offer.source or ""

            if len(offer.get("description", "") if isinstance(offer, dict)
                   else (offer.description or "")) > 280:
                description += "..."

            stars = score_to_stars(score)
            sc = score_to_color(score)
            src_color, src_emoji = source_label(src)
            border = "border-top:1px solid #e8eaed;" if i > 0 else ""

            html += f"""
      <div style="{border}padding:18px 0;">
        <table width="100%"><tr>
          <td>
            <span style="font-weight:700;font-size:17px;color:{sc};">
              {title}
            </span>
          </td>
          <td align="right" style="white-space:nowrap;">
            <span style="color:{sc};font-size:15px;">{stars}</span>
            <span style="color:{COLOR_MUTED};font-size:11px;
                         margin-left:4px;">{score}pts</span>
          </td>
        </tr><tr>
          <td colspan="2" style="padding:4px 0 6px;">
            <span style="color:{COLOR_MUTED};font-size:12px;">
              {'🏢 ' + company if company else ''}
              {'&nbsp;|&nbsp;' if company and location else ''}
              {'📍 ' + location if location else ''}
            </span>
          </td>
        </tr><tr>
          <td colspan="2" style="padding-bottom:8px;">
            <span style="display:inline-block;background:#e8f0fe;
                         color:{COLOR_PRIMARY};font-size:11px;
                         padding:2px 8px;border-radius:12px;
                         margin-right:4px;">{contract}</span>
            <span style="display:inline-block;background:#fce8e6;
                         color:{COLOR_LOW};font-size:11px;
                         padding:2px 8px;border-radius:12px;
                         margin-right:4px;">💶 {salary}</span>
            <span style="display:inline-block;background:white;
                         border:1px solid {src_color};
                         color:{src_color};font-size:10px;
                         padding:2px 7px;border-radius:12px;">
              {src_emoji} {src.split(':')[0]}
            </span>
          </td>
        </tr><tr>
          <td colspan="2" style="padding-bottom:10px;">
            <p style="margin:0;color:{COLOR_TEXT};font-size:13px;
                      line-height:1.55;">{description}</p>
          </td>
        </tr><tr>
          <td colspan="2">
            <a href="{url}"
               style="display:inline-block;background:{COLOR_PRIMARY};
                      color:#fff;font-size:13px;font-weight:700;
                      padding:7px 16px;border-radius:4px;
                      text-decoration:none;">Voir l'offre →</a>
          </td>
        </tr></table>
      </div>"""

    if nb > max_offers:
        html += f"""
      <p style="color:{COLOR_MUTED};font-size:12px;text-align:center;
                border-top:1px solid #e8eaed;padding-top:12px;">
        + {nb - max_offers} offre(s) supplémentaire(s) dans la base
      </p>"""

    html += f"""
    </td>
  </tr>
  <tr>
    <td style="padding:16px 0;text-align:center;">
      <p style="color:{COLOR_MUTED};font-size:11px;margin:0;">
        JobBot &mdash; {today} &mdash; Veille automatisée<br>
        Les candidatures restent sous ta responsabilité.
      </p>
    </td>
  </tr>
</table></td></tr></table>
</body></html>"""

    return html


def generate_text_report(
    offers: list, stats: dict, config: dict, source_counts: dict = None
) -> str:
    """Version texte brut du rapport (fallback si HTML non supporté)."""
    today = date.today().strftime("%d/%m/%Y")
    max_offers = config.get("email", {}).get("max_offers_in_email", 25)
    source_counts = source_counts or {}

    lines = [
        f"JOBBOT — OFFRES DU JOUR — {today}",
        "=" * 60,
        f"Nouvelles offres : {len(offers)}",
        f"Total en base    : {stats.get('total', 0)}",
        f"Candidatures     : {stats.get('applied', 0)}",
    ]

    if source_counts:
        lines.append("")
        lines.append("Sources :")
        for src, count in sorted(
            source_counts.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"  • {src:<20} {count} offres")

    lines += ["=" * 60, ""]

    if not offers:
        lines.append("Aucune nouvelle offre aujourd'hui.")
        return "\n".join(lines)

    for i, offer in enumerate(offers[:max_offers], 1):
        if isinstance(offer, dict):
            title = offer.get("title", "")
            company = offer.get("company") or "N/A"
            location = offer.get("location") or "N/A"
            contract = offer.get("contract") or "N/A"
            salary = offer.get("salary") or "N/A"
            url = offer.get("url", "")
            score = offer.get("score", 0)
            src = offer.get("source", "")
        else:
            title = offer.title or ""
            company = offer.company or "N/A"
            location = offer.location or "N/A"
            contract = offer.contract or "N/A"
            salary = offer.salary or "N/A"
            url = offer.url
            score = offer.score
            src = offer.source or ""

        lines += [
            f"[{i:02d}] {title}",
            f"     Score    : {score_to_stars(score)} ({score}pts)"
            f"  [{src}]",
            f"     Société  : {company}",
            f"     Lieu     : {location}",
            f"     Contrat  : {contract}",
            f"     Salaire  : {salary}",
            f"     Lien     : {url}",
            "",
        ]

    lines += [
        "-" * 60,
        "JobBot — Les candidatures restent sous ta responsabilité.",
    ]
    return "\n".join(lines)
