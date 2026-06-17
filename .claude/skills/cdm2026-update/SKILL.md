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
    { title: 'Collecte', detail: '4 agents disjoints, delta-only, 2-3 sources autoritaires' },
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
Sources autoritaires à privilégier : site officiel FIFA (fifa.com/worldcup) et Wikipédia ;
recoupe les scores avec BBC Sport ou ESPN en cas de doute. Ne renvoie QUE des FAITS NOUVEAUX
(matchs joués depuis la dernière MAJ et non déjà enregistrés). Renvoie un objet, pas de prose.`

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
const LINEUP = {
  type: 'object',
  properties: {
    match: { type: 'string' }, team: { type: 'string' }, formation: { type: 'string' },
    raw: { type: 'string', description: 'XI titulaire : GK; def; mid; att séparés par ;' },
    players: { type: 'array', items: { type: 'string' } },
    subs: { type: 'array', items: { type: 'string' } }, coach: { type: 'string' },
  },
  required: ['match', 'team', 'formation'],
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

// ─── PHASE 1 : COLLECTE DELTA (4 agents disjoints, en parallèle) ─────────────
phase('Collecte')

const collectors = [
  // 1) Résultats + planning (sources autoritaires, recoupées)
  () => agent(
    `${CONTEXT}\n\nTâche : liste les MATCHS JOUÉS depuis la dernière MAJ et non déjà enregistrés
(scores exacts, date, stade, ville, affluence ; prolongation/tab si knockout). Inclus aussi les
mises à jour de planning (matchs désormais programmés avec date/lieu). Mets à jour meta.current_phase
et meta.last_updated (date ISO du jour de collecte).`,
    { label: 'results', phase: 'Collecte',
      schema: { type: 'object', properties: {
        matches: { type: 'array', items: MATCH },
        meta: { type: 'object', properties: { current_phase: { type: 'string' }, last_updated: { type: 'string' } } },
      }, required: ['matches'] } }
  ),
  // 2) Buteurs + cartons des nouveaux matchs
  () => agent(
    `${CONTEXT}\n\nTâche : pour CHAQUE nouveau match joué uniquement, liste les événements :
buts (type goal/pen, ou own_goal avec benefits = équipe qui marque), cartons jaunes et rouges.
Donne le buteur/joueur, son équipe (nom complet français), la minute, et le motif pour les rouges.`,
    { label: 'scorers-cards', phase: 'Collecte',
      schema: { type: 'object', properties: { events: { type: 'array', items: EVENT } }, required: ['events'] } }
  ),
  // 3) Blessures, retours, forme & engagement (qualitatif)
  () => agent(
    `${CONTEXT}\n\nTâche : collecte l'actualité d'avant prochains matchs :
- blessures NOUVELLES ou MODIFIÉES (status out/doubtful/returning ; resolved si un joueur revient de blessure) ;
- forme des équipes (form_notes : note courte + tendance up/down/stable) et joueurs en forme/méforme (player_form) ;
- engagement/enjeu (engagement_notes : qualification acquise ? turnover probable ? ce que l'équipe doit faire ?).
Ne renvoie que ce qui a changé ou est pertinent pour le pronostic.`,
    { label: 'injuries-form', phase: 'Collecte',
      schema: { type: 'object', properties: {
        injuries: { type: 'array', items: INJURY },
        form_notes: { type: 'array', items: NOTE },
        player_form: { type: 'array', items: NOTE },
        engagement_notes: { type: 'array', items: NOTE },
      } } }
  ),
  // 4) Compositions des nouveaux matchs
  () => agent(
    `${CONTEXT}\n\nTâche : pour CHAQUE nouveau match joué uniquement, donne la composition de DÉPART
des deux équipes : formation (ex 4-3-3), XI titulaire dans raw (GK; défenseurs; milieux; attaquants
séparés par des points-virgules), liste players à plat, remplaçants entrés (subs) et le coach.`,
    { label: 'lineups', phase: 'Collecte',
      schema: { type: 'object', properties: { lineups: { type: 'array', items: LINEUP } }, required: ['lineups'] } }
  ),
]

const [res, evs, inj, lus] = await parallel(collectors)

// ─── PHASE 2 : FUSION (JS pur, 0 agent) ──────────────────────────────────────
phase('Fusion')

const delta = {
  meta: (res && res.meta) || {},
  matches: (res && res.matches) || [],
  events: (evs && evs.events) || [],
  lineups: (lus && lus.lineups) || [],
  injuries: (inj && inj.injuries) || [],
  form_notes: (inj && inj.form_notes) || [],
  player_form: (inj && inj.player_form) || [],
  engagement_notes: (inj && inj.engagement_notes) || [],
}

const newMatches = delta.matches.filter(m => m.status === 'played').length
log(`Delta prêt : ${newMatches} nouveau(x) match(s) joué(s), ${delta.events.length} événement(s), ` +
    `${delta.lineups.length} compo(s), ${delta.injuries.length} blessure(s).`)

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
