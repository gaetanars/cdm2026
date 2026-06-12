---
name: cdm2026-update
description: |
  Met à jour le fichier resultat_cdm2026.txt avec les résultats, classements et statistiques joueurs de la Coupe du Monde 2026. Lance un workflow en deux phases : recherche web multi-sources (10+ sites, 5+ langues, 4 continents) puis mise à jour structurée du fichier. Utilise ce skill dès que l'utilisateur mentionne : "mets à jour les résultats CDM", "update cdm2026", "résultats coupe du monde 2026", "cdm2026 update", "/cdm2026-update", "mise à jour CDM", "world cup 2026 results", "actualise les matchs", ou toute demande de mise à jour liée à la Coupe du Monde FIFA 2026. Déclencher également si l'utilisateur demande des résultats, classements ou stats de la CDM 2026, même sans mentionner explicitement le skill.
---

# CDM 2026 — Mise à jour des résultats

Ce skill orchestre deux phases via le **Workflow tool** :
1. **Recherche Web** — agents parallèles sur 10+ sources, 5+ langues, 4 continents
2. **Mise à jour fichier** — consolidation et écriture dans `resultat_cdm2026.txt`

---

## Instructions d'exécution

Dès que ce skill est déclenché, appelle immédiatement le **Workflow tool** avec le script ci-dessous. Ne résume pas, ne demande pas de confirmation — lance le workflow directement.

Le fichier cible est : `resultat_cdm2026.txt` dans le répertoire courant.

---

## Script Workflow à utiliser

```javascript
export const meta = {
  name: 'cdm2026-update',
  description: 'Recherche web multi-sources CDM 2026 et mise à jour du fichier de résultats',
  phases: [
    { title: 'Recherche Web', detail: 'Scraping parallèle 10+ sources, 5+ langues, 4 continents' },
    { title: 'Consolidation', detail: 'Fusion et déduplication des données collectées' },
    { title: 'Mise à jour fichier', detail: 'Écriture structurée dans resultat_cdm2026.txt' },
  ],
}

// ─── PHASE 1 : RECHERCHE WEB PARALLÈLE ───────────────────────────────────────
phase('Recherche Web')

const SEARCH_TARGETS = [
  // Europe — Français
  {
    label: 'lequipe-fr',
    lang: 'fr',
    continent: 'Europe',
    prompt: `Tu es un agent de collecte de données sportives. Recherche sur le site lequipe.fr et sur google.fr tous les résultats de matchs de la Coupe du Monde 2026 (FIFA World Cup 2026) : scores exacts, dates, stades, phases (groupes, huitièmes, quarts, demi-finales, finale). Inclus aussi les classements des groupes avec points et différence de buts. Retourne UNIQUEMENT les données brutes structurées, pas de commentaires. Format souhaité : liste JSON avec {phase, groupe, match_num, date, stade, equipe1, score1, score2, equipe2}.`
  },
  // Europe — Anglais
  {
    label: 'bbc-sport-en',
    lang: 'en',
    continent: 'Europe',
    prompt: `You are a sports data collection agent. Search BBC Sport (bbc.com/sport/football/world-cup), UEFA, and Sky Sports for all FIFA World Cup 2026 match results: exact scores, dates, venues, competition phase (group stage, round of 32, round of 16, quarter-finals, semi-finals, final). Also retrieve group standings (points, goal difference, goals for/against). Return only structured raw data. Format: JSON list with {phase, group, match_num, date, venue, team1, score1, score2, team2}.`
  },
  // Europe — Espagnol
  {
    label: 'marca-es',
    lang: 'es',
    continent: 'Europe',
    prompt: `Eres un agente de recopilación de datos deportivos. Busca en Marca (marca.com), AS (as.com) y Mundo Deportivo todos los resultados de partidos del Mundial 2026 (FIFA World Cup 2026): marcadores exactos, fechas, estadios, fases. También obtén las clasificaciones de grupos con puntos y diferencia de goles. Devuelve solo datos estructurados en bruto. Formato: lista JSON con {fase, grupo, num_partido, fecha, estadio, equipo1, goles1, goles2, equipo2}.`
  },
  // Amériques — Portugais
  {
    label: 'globoesporte-pt',
    lang: 'pt',
    continent: 'Amériques',
    prompt: `Você é um agente de coleta de dados esportivos. Pesquise no GloboEsporte (ge.globo.com), UOL Esporte e ESPN Brasil todos os resultados de jogos da Copa do Mundo 2026 (FIFA World Cup 2026): placares exatos, datas, estádios, fases. Inclua também as classificações dos grupos com pontos e saldo de gols. Retorne apenas dados estruturados brutos. Formato: lista JSON com {fase, grupo, num_jogo, data, estadio, time1, gols1, gols2, time2}.`
  },
  // Amériques — Anglais/Espagnol
  {
    label: 'espn-americas',
    lang: 'en',
    continent: 'Amériques',
    prompt: `You are a sports data collection agent. Search ESPN (espn.com/soccer/world-cup), MLS official site, and Univision Deportes for all FIFA World Cup 2026 match results and group standings. This World Cup is co-hosted by USA, Canada, and Mexico. Return structured JSON: {phase, group, match_num, date, venue, city, country, team1, score1, score2, team2, attendance}.`
  },
  // Asie — Japonais/Anglais
  {
    label: 'yomiuri-japan',
    lang: 'ja',
    continent: 'Asie',
    prompt: `You are a sports data collection agent. Search NHK Sport (sports.nhk.or.jp), Yomiuri Shimbun sports section, and Yahoo Japan Sports for FIFA World Cup 2026 (FIFAワールドカップ2026) all match results, group standings, and Asian teams performance (Japan, South Korea, Saudi Arabia, Australia, Iran, Morocco). Return structured JSON with {phase, group, match_num, date, venue, team1, score1, score2, team2}.`
  },
  // Afrique/Moyen-Orient — Arabe/Anglais
  {
    label: 'al-jazeera-ar',
    lang: 'ar',
    continent: 'Afrique/Moyen-Orient',
    prompt: `You are a sports data collection agent. Search Al Jazeera Sport (sport.aljazeera.net), beIN Sports Arabic, and SuperSport Africa for all FIFA World Cup 2026 match results and standings. Focus especially on African teams (Morocco, Senegal, Egypt, Nigeria, Cameroon) and Middle Eastern teams (Saudi Arabia, Qatar, Iran). Return structured JSON: {phase, group, match_num, date, venue, team1, score1, score2, team2}.`
  },
  // FIFA officiel
  {
    label: 'fifa-official',
    lang: 'en',
    continent: 'International',
    prompt: `You are a sports data collection agent. Search the official FIFA website (fifa.com/worldcup/2026) and Wikipedia for the complete and authoritative list of all FIFA World Cup 2026 match results, group standings, knockout bracket, and schedule. Also retrieve: top scorers list, disciplinary summary (red/yellow cards by team), and injury reports if available. Return structured JSON.`
  },
  // Stats joueurs — buts et cartons
  {
    label: 'player-stats-goals-cards',
    lang: 'en',
    continent: 'International',
    prompt: `You are a sports statistics agent. Search Transfermarkt (transfermarkt.com), WhoScored (whoscored.com), SofaScore (sofascore.com), and FBref (fbref.com) for FIFA World Cup 2026 individual player statistics: 1) Goals scored by player (player name, team, total goals, matches scored in), 2) Yellow cards by player (player name, team, count, which matches), 3) Red cards by player (player name, team, which match), 4) Injuries during the tournament (player, team, injury type, matches missed). Return structured JSON arrays for each category.`
  },
  // Compositions et tactiques
  {
    label: 'lineups-tactics',
    lang: 'en',
    continent: 'International',
    prompt: `You are a football tactics and lineup data agent. Search SofaScore (sofascore.com/tournament/football/world/world-cup-2026), Fotmob, and FlashScore for FIFA World Cup 2026 starting lineups for every match played: formation (e.g. 4-3-3), goalkeeper, defenders, midfielders, forwards, substitutes, and coach. Format: JSON array where each element is {match_id, date, team, formation, lineup: [player_name, position], substitutes: [player_name], coach}. Include both teams for each match.`
  },
]

const researchResults = await parallel(
  SEARCH_TARGETS.map(target => () =>
    agent(target.prompt, {
      label: target.label,
      phase: 'Recherche Web',
    })
  )
)

const validResults = researchResults.filter(Boolean)
log(`Recherche terminée : ${validResults.length}/${SEARCH_TARGETS.length} sources collectées`)

// ─── PHASE 2 : CONSOLIDATION ──────────────────────────────────────────────────
phase('Consolidation')

const consolidated = await agent(
  `Tu es un agent de consolidation de données sportives pour la Coupe du Monde 2026.

Tu reçois les données brutes de ${validResults.length} sources différentes (sites web en français, anglais, espagnol, portugais, japonais, arabe). Certaines sources peuvent être partielles ou se contredire légèrement.

DONNÉES COLLECTÉES :
${validResults.map((r, i) => `--- Source ${i + 1} (${SEARCH_TARGETS[i]?.label || 'unknown'}) ---\n${r}`).join('\n\n')}

Ta tâche : consolider toutes ces données en un seul objet JSON structuré et fiable. En cas de contradiction entre sources, favorise les données officielles FIFA puis BBC/ESPN. Note les incertitudes avec un champ "confidence": "high"/"medium"/"low".

Retourne un JSON avec cette structure EXACTE :
{
  "last_updated": "ISO date string",
  "tournament_phase": "current phase name",
  "groups": {
    "A": {
      "matches": [{"num": 1, "date": "YYYY-MM-DD", "venue": "...", "city": "...", "team1": "...", "score1": N, "score2": N, "team2": "...", "phase": "Groupe", "confidence": "high"}],
      "standings": [{"rank": 1, "team": "...", "pts": N, "played": N, "won": N, "drawn": N, "lost": N, "gf": N, "ga": N, "gd": N}]
    },
    "B": { ... },
    ...
  },
  "knockout": [
    {"round": "Huitièmes", "match_num": 1, "date": "...", "venue": "...", "team1": "...", "score1": N, "score2": N, "team2": "...", "extra_time": false, "penalties": null}
  ],
  "player_stats": {
    "FRANCE": {
      "goals": [{"player": "...", "count": N, "matches": ["vs XXX"]}],
      "yellow_cards": [{"player": "...", "count": N, "matches": ["vs XXX"]}],
      "red_cards": [{"player": "...", "match": "vs XXX"}],
      "injuries": [{"player": "...", "type": "...", "severity": "...", "matches_missed": ["vs XXX"]}],
      "lineups": [
        {"match": "vs XXX", "date": "...", "formation": "4-3-3", "players": ["Maignan", "..."], "subs": ["..."]}
      ]
    }
  },
  "top_scorers": [{"player": "...", "team": "...", "goals": N}],
  "disciplinary": {"most_carded_team": "...", "total_yellows": N, "total_reds": N}
}`,
  { label: 'consolidation', phase: 'Consolidation' }
)

log('Consolidation terminée')

// ─── PHASE 3 : MISE À JOUR FICHIER ───────────────────────────────────────────
phase('Mise à jour fichier')

await agent(
  `Tu es un agent de rédaction de rapports sportifs. Tu dois mettre à jour le fichier resultat_cdm2026.txt avec les données consolidées de la Coupe du Monde 2026.

DONNÉES CONSOLIDÉES (JSON) :
${consolidated}

INSTRUCTIONS IMPORTANTES :
1. Lis d'abord le fichier existant resultat_cdm2026.txt (s'il existe) pour conserver le contenu déjà présent
2. Mets à jour ou ajoute les sections avec les nouvelles données
3. Ne supprime aucune section déjà présente sauf si les données sont incorrectes
4. Utilise EXACTEMENT le format spécifié ci-dessous
5. Le fichier doit être lisible par un agent autonome de pronostic — la structure doit être 100% cohérente et sans ambiguïté
6. Chaque section doit commencer par un marqueur entre crochets comme [PHASE DE GROUPES - GROUPE A]
7. Pour les équipes sans données (pas encore jouées), écrire "Aucun match joué"

FORMAT OBLIGATOIRE DU FICHIER :

===========================================================================
COUPE DU MONDE FIFA 2026 — BASE DE DONNÉES RÉSULTATS
Dernière mise à jour : {DATE_HEURE_ISO}
Sources : FIFA.com, BBC Sport, L'Équipe, Marca, GloboEsporte, ESPN, SofaScore, Transfermarkt + 3 autres
Langues consultées : Français, Anglais, Espagnol, Portugais, Japonais, Arabe
===========================================================================

[PHASE DE GROUPES - GROUPE A]
Match 1 : {equipe1} {score1} - {score2} {equipe2} ({date}, {stade}, {ville})
Match 2 : {equipe1} {score1} - {score2} {equipe2} ({date}, {stade}, {ville})
Match 3 : {equipe1} {score1} - {score2} {equipe2} ({date}, {stade}, {ville})
Classement provisoire Groupe A : 1. {equipe} ({pts}pt, {gd:+/-N}), 2. {equipe} ({pts}pt, {gd}), 3. {equipe} ({pts}pt, {gd}), 4. {equipe} ({pts}pt, {gd})

[PHASE DE GROUPES - GROUPE B]
...

[PHASE ÉLIMINATOIRE - HUITIÈMES DE FINALE]
Match H1 : {equipe1} {score1} - {score2} {equipe2} ({date}, {stade}) [Prolong. si applicable] [Tab {N}-{N} si applicable]
...

[PHASE ÉLIMINATOIRE - QUARTS DE FINALE]
...

[PHASE ÉLIMINATOIRE - DEMI-FINALES]
...

[FINALE]
...

[CLASSEMENT BUTEURS]
1. {joueur} ({équipe}) — {N} buts
2. ...

[STATISTIQUES PAR ÉQUIPE]

=== {NOM_EQUIPE_EN_MAJUSCULES} ===
Buts : {joueur} ({N}), {joueur} ({N}), ... | Total équipe : {N}
Cartons jaunes : {joueur} ({N}, vs {adversaire}), ... | Total : {N}
Cartons rouges : {joueur} (vs {adversaire}, {minute}') | Total : {N}
Blessures : {joueur} ({type}, forfait vs {adversaire}), ... | Joueurs indisponibles : {N}
Compositions alignées :
  Match 1 vs {adversaire} ({date}) : {formation} — {GK}; {DEF1}, {DEF2}, {DEF3}, {DEF4}; {MID1}, {MID2}, {MID3}; {ATT1}, {ATT2}, {ATT3}
  Match 2 vs {adversaire} ({date}) : {formation} — ...
Composition la plus fréquente : {formation}
Joueurs clés : {joueur} ({role}), {joueur} ({role})

[ANALYSE PRONOSTIC]
— Équipes les mieux classées : {liste}
— Équipes en forme (0 défaite) : {liste}
— Équipes avec blessures importantes : {liste}
— Cartons suspendus potentiels : {liste}
— Tendances défensives (moins de buts encaissés) : {liste}
— Tendances offensives (plus de buts marqués) : {liste}

===========================================================================
FIN DU FICHIER — {N} matchs enregistrés | {N} équipes documentées
===========================================================================

Écris le fichier complet à ${process.cwd()}/resultat_cdm2026.txt`,
  { label: 'file-writer', phase: 'Mise à jour fichier' }
)

log('Fichier resultat_cdm2026.txt mis à jour avec succès')
return { status: 'success', message: 'resultat_cdm2026.txt mis à jour' }
```

---

## Notes d'utilisation

- **Durée estimée** : 3-6 minutes (recherches parallèles sur 10 sources)
- **En cas d'échec partiel** : le script continue avec les sources disponibles — une source inaccessible ne bloque pas les autres
- **Mise à jour incrémentale** : si le fichier existe déjà, seules les nouvelles données sont ajoutées ; les données existantes correctes sont préservées
- **Fiabilité des données** : les contradictions entre sources sont signalées via le champ `confidence` dans le JSON intermédiaire, et l'agent de rédaction favorise les sources officielles (FIFA > BBC/ESPN > autres)
- **Format machine-readable** : les marqueurs `[...]` et `===...===` permettent un parsing simple par regex pour un agent de pronostic en aval
