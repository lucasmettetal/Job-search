# Roadmap JobBot

## V1 — Veille quotidienne ✅
- [x] Récupération des offres via API France Travail
- [x] Système de scoring par mots-clés
- [x] Anti-doublons (SQLite)
- [x] Email HTML quotidien
- [x] Configuration YAML sans toucher au code

## V2 — Analyse IA des offres
- [ ] Résumé automatique de chaque offre avec l'API Claude/OpenAI
- [ ] Détection des compétences requises (extraction NLP)
- [ ] Score de compatibilité CV / offre
- [ ] Alerte si offre "parfaite" (score > seuil)

## V3 — Génération de candidature
- [ ] Génération de lettre de motivation personnalisée par offre
- [ ] Adaptation du CV selon les mots-clés de l'offre
- [ ] Génération d'un mail de candidature
- [ ] Export PDF (WeasyPrint ou ReportLab)

## V4 — Interface web (Streamlit)
- [ ] Dashboard des offres avec filtres
- [ ] Bouton "Préparer ma candidature"
- [ ] Aperçu du mail/LM générés avant envoi
- [ ] Suivi des candidatures :
  - À postuler
  - Postulé
  - Relancé
  - Entretien planifié
  - Refusé
  - Accepté

## V5 — Sources supplémentaires
- [ ] Welcome to the Jungle (API ou RSS)
- [ ] Apec.fr
- [ ] LinkedIn (alertes email uniquement, pas de scraping)
- [ ] Indeed RSS feed
- [ ] Remotive.io (remote jobs)
