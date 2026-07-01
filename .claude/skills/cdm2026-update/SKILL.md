---
name: cdm2026-update
description: |
  Met à jour le fichier resultat_cdm2026.txt avec les résultats, classements et statistiques joueurs de la Coupe du Monde 2026. Lance un workflow en deux phases : recherche web multi-sources (10+ sites, 5+ langues, 4 continents) puis mise à jour structurée du fichier. Utilise ce skill dès que l'utilisateur mentionne : "mets à jour les résultats CDM", "update cdm2026", "résultats coupe du monde 2026", "cdm2026 update", "/cdm2026-update", "mise à jour CDM", "world cup 2026 results", "actualise les matchs", ou toute demande de mise à jour liée à la Coupe du Monde FIFA 2026. Déclencher également si l'utilisateur demande des résultats, classements ou stats de la CDM 2026, même sans mentionner explicitement le skill.
---

# CDM 2026 — Mise à jour des résultats (architecture delta, économe en tokens)

## Principe

La **source de vérité** est `cdm2026.json` (faits atomiques uniquement). Le fichier
lisible `resultat_cdm2026.txt` est **généré** par `cdm2026_tool.py`, jamais édité à la main.

> Les agents LLM ne récupèrent que des **faits bruts NOUVEAUX** depuis le web.
> Tout le dérivé (classements, buteurs, totaux cartons, suspensions, stats globales,
> agrégats de pronostic) est **calculé en Python** → cohérence arithmétique garantie,
> aucune hallucination, et le coût en tokens ne dépend que des **nouveaux** matchs.

Ce que ça remplace (ancien workflow) : 10 agents collectant chacun TOUT le tournoi en
6 langues + 1 agent de consolidation recevant 10 dumps + 1 agent réécrivant 50 Ko.
Désormais : 4 agents disjoints **delta-only**, fusion en JS, rendu déterministe.

---

## Procédure d'exécution (4 étapes)

Le répertoire courant contient `cdm2026.json`, `cdm2026_tool.py`, `resultat_cdm2026.txt`.

### Étape 1 — Lire l'état courant (Bash, ~0 token)
```bash
python3 cdm2026_tool.py state
```
Récupère `last_updated`, `current_phase`, `played_match_ids` (matchs déjà figés,
immuables) et `next_matches`. Garde ce JSON : il sert de **frontière** — les agents ne
collecteront QUE ce qui n'est pas déjà dans `played_match_ids`.

### Étape 2 — Lancer le Workflow de collecte delta
Appelle le **Workflow tool** avec le script ci-dessous, en passant l'objet `state` de
l'étape 1 comme `args`. Le workflow renvoie un objet `delta` (faits nouveaux uniquement).

### Étape 3 — Écrire le delta
Écris l'objet `delta` retourné dans `delta.json` (via le Write tool).

### Étape 4 — Fusionner + régénérer (Bash, ~0 token)
```bash
python3 cdm2026_tool.py merge delta.json
```
`merge` fait l'upsert (matchs joués = immuables, aucun doublon), recalcule TOUT le
dérivé, et régénère `resultat_cdm2026.txt`. Puis supprime `delta.json`.

Si aucun nouveau match n'est trouvé, n'écris pas de delta et signale-le simplement.

---

## Script Workflow

```javascript
export const meta = {
  name: 'cdm2026-update',
  description: 'Collecte delta multi-sources CDM 2026 (faits nouveaux uniquement)',
  phases: [
    { title: 'Collecte', detail: '2 agents WebSearch-only, delta-only' },
    { title: 'Fusion', detail: 'Assemblage JS des fragments en un delta unique' },
  ],
}

// L'état courant (sortie de `cdm2026_tool.py state`) passé en args.
const state = args || {}
const frozen = (state.played_match_ids || []).join(', ') || 'aucun'
const since = state.last_updated || 'le début du tournoi'
const currentPhase = state.current_phase || 'inconnue'

const CONTEXT = `CONTEXTE CDM 2026 (USA/Canada/Mexique).
Phase actuelle : ${currentPhase}.
Dernière mise à jour : ${since}.
Matchs DÉJÀ enregistrés (NE PAS recollecter, ils sont figés) : ${frozen}.
IMPORTANT : utilise UNIQUEMENT WebSearch (jamais WebFetch). Les snippets des résultats
de recherche suffisent pour extraire les faits. Si un score est ambigu, lance une
2e WebSearch plus ciblée. Ne tente PAS de fetcher les pages complètes.
Sources à privilégier dans les queries : FIFA, BBC Sport, ESPN, SofaScore.
Ne renvoie QUE des FAITS NOUVEAUX (matchs joués depuis la dernière MAJ et non déjà
enregistrés dans played_match_ids). Renvoie un objet structuré, pas de prose.`

// ─── Schemas (sortie compacte validée) ──────────────────────────────────────
const MATCH = {
  type: 'object',
  properties: {
    id: { type: 'string', description: 'Lettre groupe + n° (ex A3) ou code knockout (ex R16-1)' },
    phase: { type: 'string', enum: ['group', 'knockout'] },
    group: { type: 'string' },
    round: { type: 'string', description: 'Huitièmes/Quarts/Demi-finales/Finale si knockout' },
    date: { type: 'string' }, venue: { type: 'string' }, city: { type: 'string' },
    home: { type: 'string' }, away: { type: 'string' },
    status: { type: 'string', enum: ['played', 'scheduled'] },
    score: { type: 'array', items: { type: 'integer' }, description: '[buts_home, buts_away]' },
    et: { type: 'boolean' }, pens: { type: 'array', items: { type: 'integer' } },
    attendance: { type: 'integer' },
  },
  required: ['id', 'home', 'away', 'status'],
}
const EVENT = {
  type: 'object',
  properties: {
    match: { type: 'string' }, team: { type: 'string', description: 'Nom complet français' },
    player: { type: 'string' }, minute: { type: 'string', description: "ex 45 ou 90+2" },
    type: { type: 'string', enum: ['goal', 'pen', 'own_goal', 'yellow', 'red'] },
    benefits: { type: 'string', description: 'Pour own_goal : équipe qui marque' },
    detail: { type: 'string' },
  },
  required: ['match', 'team', 'player', 'type'],
}
const INJURY = {
  type: 'object',
  properties: {
    team: { type: 'string' }, player: { type: 'string' }, type: { type: 'string' },
    severity: { type: 'string', enum: ['minor', 'moderate', 'severe'] },
    status: { type: 'string', enum: ['out', 'doubtful', 'returning', 'resolved'] },
    note: { type: 'string' },
  },
  required: ['team', 'player', 'status'],
}
const NOTE = {
  type: 'object',
  properties: {
    team: { type: 'string' }, player: { type: 'string' }, note: { type: 'string' },
    trend: { type: 'string', enum: ['up', 'down', 'stable'] },
  },
  required: ['team', 'note'],
}

// ─── PHASE 1 : COLLECTE DELTA (2 agents WebSearch-only, en parallèle) ────────
phase('Collecte')

const [factuel, qualitatif] = await parallel([
  // Agent 1 — Résultats & événements (scores, buts, cartons)
  () => agent(
    `${CONTEXT}\n\nTâche A — Faits de match :
1. Lance des WebSearch ciblées (ex : "FIFA World Cup 2026 results ${since}", "CDM 2026 scores today") pour trouver les matchs joués depuis la dernière MAJ et non dans played_match_ids.
2. Pour chaque nouveau match joué : score exact, date, stade, ville, affluence, prolongation/pénos si knockout.
3. Pour chaque nouveau match joué : tous les événements (buts avec buteur+équipe+minute, cartons jaunes/rouges avec joueur+équipe+minute, buts contre son camp avec equipe qui marque).
4. Mets à jour meta.current_phase et meta.last_updated (date ISO du jour).
Si aucun nouveau match : retourne matches:[] et events:[].`,
    { label: 'results-events', phase: 'Collecte',
      schema: { type: 'object', properties: {
        matches: { type: 'array', items: MATCH },
        events: { type: 'array', items: EVENT },
        meta: { type: 'object', properties: { current_phase: { type: 'string' }, last_updated: { type: 'string' } } },
      }, required: ['matches', 'events'] } }
  ),
  // Agent 2 — Qualitatif (blessures, forme, enjeux)
  () => agent(
    `${CONTEXT}\n\nTâche B — Actualité avant prochains matchs :
1. Lance des WebSearch (ex : "World Cup 2026 injury news", "CDM 2026 blessures", "FIFA 2026 team news") pour l'actualité récente.
2. Blessures NOUVELLES ou MODIFIÉES seulement (status out/doubtful/returning/resolved).
3. Forme des équipes qui jouent prochainement (form_notes : tendance up/down/stable + raison courte).
4. Joueurs en forme ou méforme notable (player_form).
5. Engagement/enjeux (qualification acquise ? turnover probable ? stakes ?).
Ne renvoie que ce qui a changé depuis ${since} ou est directement pertinent pour le pronostic.`,
    { label: 'injuries-form', phase: 'Collecte',
      schema: { type: 'object', properties: {
        injuries: { type: 'array', items: INJURY },
        form_notes: { type: 'array', items: NOTE },
        player_form: { type: 'array', items: NOTE },
        engagement_notes: { type: 'array', items: NOTE },
      } } }
  ),
])

// ─── PHASE 2 : FUSION (JS pur, 0 agent) ──────────────────────────────────────
phase('Fusion')

const delta = {
  meta: (factuel && factuel.meta) || {},
  matches: (factuel && factuel.matches) || [],
  events: (factuel && factuel.events) || [],
  lineups: [],
  injuries: (qualitatif && qualitatif.injuries) || [],
  form_notes: (qualitatif && qualitatif.form_notes) || [],
  player_form: (qualitatif && qualitatif.player_form) || [],
  engagement_notes: (qualitatif && qualitatif.engagement_notes) || [],
}

const newMatches = delta.matches.filter(m => m.status === 'played').length
log(`Delta prêt : ${newMatches} nouveau(x) match(s) joué(s), ${delta.events.length} événement(s), ${delta.injuries.length} blessure(s).`)

return delta
```

---

## Après le workflow

1. Récupère l'objet `delta` retourné par le workflow.
2. **Écris-le** dans `delta.json` (Write tool).
3. Exécute `python3 cdm2026_tool.py merge delta.json`.
4. Supprime `delta.json` et rapporte le résumé du merge à l'utilisateur.

Si `delta.matches` (joués) est vide ET qu'il n'y a ni blessure ni forme nouvelle,
inutile d'écrire/fusionner : signale qu'il n'y a rien de nouveau depuis `last_updated`.

---

## Outil `cdm2026_tool.py` (référence)

| Commande | Effet | Tokens |
|----------|-------|--------|
| `state` | Index compact (frontière : matchs figés, phase, prochains matchs) | ~0 |
| `merge <delta.json>` | Upsert sans doublon (matchs joués immuables) + recalcul + rendu | ~0 |
| `render` | Régénère `resultat_cdm2026.txt` depuis le JSON | ~0 |
| `bootstrap [txt]` | Reconstruit le JSON depuis l'ancien `.txt` (migration ponctuelle) | ~0 |

**Tout le dérivé est calculé** (classements, buteurs, totaux cartons, suspensions par
cumul/rouge, scénarios d'engagement, stats globales, agrégats de pronostic) : ne JAMAIS
demander ces valeurs aux agents — elles seraient incohérentes. Les agents ne fournissent
que des faits bruts ; le `.txt` final contient des sections enrichies générées
automatiquement : `[FORME ET DYNAMIQUE]`, `[ENGAGEMENT ET ENJEUX]`,
`[SUSPENSIONS ET DISPONIBILITÉS À VENIR]`, `[ANALYSE PRONOSTIC]`.

## Notes

- **Économe** : le coût scale avec les NOUVEAUX matchs, pas avec la taille du fichier.
- **Échec partiel** : un agent qui renvoie `null` n'empêche pas les autres (filtré au merge).
- **Cohérence** : les contradictions de scores sont arbitrées par les agents (FIFA > BBC/ESPN) ;
  tous les agrégats sont recalculés, donc toujours cohérents avec les faits enregistrés.
- **Idempotent** : relancer sans nouveau match ne change rien (upsert + dédup).
