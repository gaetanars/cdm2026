#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cdm2026_tool.py — Outil déterministe pour la base de résultats CDM 2026.

Source de vérité : cdm2026.json (faits atomiques uniquement).
Rendu lisible   : resultat_cdm2026.txt (généré, jamais édité à la main).

Sous-commandes (toutes lancées via Bash → 0 token LLM) :
  state                 Index compact (last_updated, phase, matchs joués, prochains matchs).
  merge <delta.json>    Fusionne un delta dans cdm2026.json (upsert sans doublon,
                        matchs joués immuables) puis régénère le .txt.
  render                Régénère resultat_cdm2026.txt depuis cdm2026.json.
  bootstrap [txt]       Reconstruit cdm2026.json en parsant l'ancien .txt (migration).

Principe : les LLM ne récupèrent que des FAITS BRUTS NOUVEAUX. Tout le dérivé
(classements, buteurs, totaux cartons, stats globales, suspensions, agrégats)
est CALCULÉ ici → cohérence arithmétique garantie, aucune hallucination d'agrégat.
"""

import json
import os
import re
import sys
from collections import OrderedDict, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "cdm2026.json")
TXT_PATH = os.path.join(BASE, "resultat_cdm2026.txt")
LEGACY_TXT = TXT_PATH

# Codes équipes ↔ noms (pour attribuer les événements collectés sur le web).
TEAM_CODES = {
    "MEX": "Mexique", "AFS": "Afrique du Sud", "KOR": "Corée du Sud", "TCH": "Tchéquie",
    "CAN": "Canada", "BIH": "Bosnie-Herzégovine", "QAT": "Qatar", "SUI": "Suisse",
    "BRA": "Brésil", "MAR": "Maroc", "SCO": "Écosse", "HAI": "Haïti",
    "USA": "États-Unis", "PAR": "Paraguay", "AUS": "Australie", "TUR": "Turquie",
    "GER": "Allemagne", "CUR": "Curaçao", "CIV": "Côte d'Ivoire", "ECU": "Équateur",
    "NED": "Pays-Bas", "JPN": "Japon", "SWE": "Suède", "TUN": "Tunisie",
    "BEL": "Belgique", "EGY": "Égypte", "IRN": "Iran", "NZL": "Nouvelle-Zélande",
    "ESP": "Espagne", "CPV": "Cap-Vert", "KSA": "Arabie Saoudite", "URU": "Uruguay",
    "FRA": "France", "SEN": "Sénégal", "NOR": "Norvège", "IRQ": "Irak",
    "ARG": "Argentine", "ALG": "Algérie", "AUT": "Autriche", "JOR": "Jordanie",
    "POR": "Portugal", "COL": "Colombie", "COD": "RD Congo", "UZB": "Ouzbékistan",
    "ENG": "Angleterre", "CRO": "Croatie", "GHA": "Ghana", "PAN": "Panama",
}

# ───────────────────────────── I/O ─────────────────────────────

def load():
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)

def save(data):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

def num(s):
    s = str(s).replace(" ", "").replace(" ", "").replace(" ", "")
    try:
        return int(s)
    except ValueError:
        return None

# ───────────────────────── DÉRIVATIONS ─────────────────────────
# Tout ce qui suit est PUREMENT calculé depuis les faits → cohérence garantie.

def played_matches(data):
    return [m for m in data["matches"] if m.get("status") == "played" and m.get("score")]

def team_group(data, team):
    return data["teams"].get(team, {}).get("group")

def compute_standings(data, group):
    """Classement d'un groupe, calculé depuis les matchs joués."""
    teams = [t for t, info in data["teams"].items() if info.get("group") == group]
    seed = {t: data["teams"][t].get("seed", 99) for t in teams}
    tbl = {t: dict(team=t, pts=0, pld=0, w=0, d=0, l=0, gf=0, ga=0) for t in teams}
    for m in played_matches(data):
        if m.get("group") != group:
            continue
        h, a = m["home"], m["away"]
        sh, sa = m["score"][0], m["score"][1]
        if h not in tbl or a not in tbl:
            continue
        for t, gf, ga in ((h, sh, sa), (a, sa, sh)):
            r = tbl[t]
            r["pld"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if gf > ga:
                r["w"] += 1; r["pts"] += 3
            elif gf == ga:
                r["d"] += 1; r["pts"] += 1
            else:
                r["l"] += 1
    rows = list(tbl.values())
    for r in rows:
        r["gd"] = r["gf"] - r["ga"]
    rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], seed[r["team"]]))
    return rows

def team_events(data, team, etype):
    return [e for e in data["events"] if e.get("team") == team and e.get("type") == etype]

def scorers_for_team(data, team):
    """Liste (joueur, nb) des buts marqués PAR l'équipe (hors csc adverse)."""
    cnt = OrderedDict()
    for e in data["events"]:
        if e.get("type") in ("goal", "pen") and e.get("team") == team:
            cnt[e["player"]] = cnt.get(e["player"], 0) + 1
    # buts contre son camp d'adversaires bénéficiant à cette équipe
    og = []
    for e in data["events"]:
        if e.get("type") == "own_goal" and e.get("benefits") == team:
            og.append(e)
    return cnt, og

def compute_top_scorers(data):
    cnt = defaultdict(int)
    team_of = {}
    for e in data["events"]:
        if e.get("type") in ("goal", "pen"):
            key = e["player"]
            cnt[key] += 1
            team_of[key] = e.get("team")
    ranked = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
    og = [e for e in data["events"] if e.get("type") == "own_goal"]
    return ranked, team_of, og

def team_record(data, team):
    pld = w = d = l = gf = ga = 0
    for m in played_matches(data):
        if team == m["home"]:
            mine, his = m["score"][0], m["score"][1]
        elif team == m["away"]:
            mine, his = m["score"][1], m["score"][0]
        else:
            continue
        pld += 1; gf += mine; ga += his
        if mine > his: w += 1
        elif mine == his: d += 1
        else: l += 1
    return dict(pld=pld, w=w, d=d, l=l, gf=gf, ga=ga)

def team_matches_ordered(data, team):
    ms = [m for m in data["matches"] if team in (m.get("home"), m.get("away"))]
    ms.sort(key=lambda m: (m.get("date") or "9999", m.get("id")))
    return ms

def opponent(m, team):
    return m["away"] if m["home"] == team else m["home"]

def compute_suspensions(data):
    """Suspensions pour le PROCHAIN match (rouge direct, ou 2 jaunes cumulés)."""
    out = []
    # rouges directs
    for e in data["events"]:
        if e.get("type") == "red":
            out.append(dict(player=e["player"], team=e["team"],
                            reason="rouge direct ({}{})".format(
                                e.get("minute", "?") + "'" if e.get("minute") else "",
                                ", " + e["detail"] if e.get("detail") else ""),
                            match=e.get("match")))
    # cumul de 2 jaunes dans des matchs différents (avant reset phase de groupes)
    yc = defaultdict(set)
    pteam = {}
    for e in data["events"]:
        if e.get("type") == "yellow":
            yc[e["player"]].add(e.get("match"))
            pteam[e["player"]] = e["team"]
    for player, matches in yc.items():
        if len(matches) >= 2:
            out.append(dict(player=player, team=pteam[player],
                            reason="2 cartons jaunes cumulés", match=None))
    return out

def yellow_risk(data):
    """Joueurs à 1 seul jaune (risque d'accumulation)."""
    yc = defaultdict(list)
    pteam = {}
    for e in data["events"]:
        if e.get("type") == "yellow":
            yc[e["player"]].append(e.get("match"))
            pteam[e["player"]] = e["team"]
    res = []
    for player, matches in yc.items():
        if len(matches) == 1:
            res.append((player, pteam[player], matches[0]))
    return res

def global_stats(data):
    pm = played_matches(data)
    goals = sum(m["score"][0] + m["score"][1] for m in pm)
    yellows = sum(1 for e in data["events"] if e.get("type") == "yellow")
    reds = sum(1 for e in data["events"] if e.get("type") == "red")
    att = [m.get("attendance") for m in pm if m.get("attendance")]
    return dict(
        matches=len(pm), goals=goals,
        avg=(goals / len(pm)) if pm else 0,
        yellows=yellows, reds=reds,
        att_total=sum(att), att_avg=(sum(att) // len(att)) if att else 0,
    )

# ─────────────────────────── RENDU TXT ──────────────────────────

GROUPS = list("ABCDEFGHIJKL")
KNOCKOUT_ORDER = ["Seizièmes", "Huitièmes", "Quarts", "Demi-finales", "Finale"]

def render(data):
    L = []
    w = L.append
    meta = data["meta"]
    gs = global_stats(data)
    w("=" * 75)
    w("COUPE DU MONDE FIFA 2026 — BASE DE DONNÉES RÉSULTATS")
    w("Dernière mise à jour : " + meta.get("last_updated", "N/D"))
    w("Phase actuelle : " + meta.get("current_phase", "N/D"))
    w("Matchs enregistrés (joués) : {}".format(gs["matches"]))
    w("Sources consultées : " + ", ".join(meta.get("sources", [])))
    w("=" * 75)
    w("")

    # ── Phases de groupes ──
    for g in GROUPS:
        gmatches = [m for m in data["matches"] if m.get("group") == g]
        if not gmatches:
            continue
        gmatches.sort(key=lambda m: (m.get("date") or "9999", m.get("id")))
        w("[PHASE DE GROUPES - GROUPE {}]".format(g))
        for i, m in enumerate(gmatches, 1):
            w(render_match_line(data, m, "Match {} : ".format(i)))
            if m.get("status") == "played":
                render_match_events(data, m, w)
        w(render_standings_line(data, g))
        w("")

    # ── Phases éliminatoires ──
    for label, key, datehint in [
        ("SEIZIÈMES DE FINALE (32es)", "Seizièmes", "28 juin – 3 juillet 2026"),
        ("HUITIÈMES DE FINALE", "Huitièmes", "à venir après les seizièmes"),
        ("QUARTS DE FINALE", "Quarts", "début prévu le 2026-07-09"),
        ("DEMI-FINALES", "Demi-finales", "2026-07-14 et 2026-07-15"),
    ]:
        w("[PHASE ÉLIMINATOIRE - {}]".format(label))
        kos = [m for m in data["matches"] if m.get("phase") == "knockout" and (m.get("round") or "").startswith(key)]
        if not kos:
            w("Aucun match joué ({})".format(datehint))
        else:
            for m in kos:
                w(render_match_line(data, m, ""))
                if m.get("status") == "played":
                    render_match_events(data, m, w)
        w("")

    # ── Finale ──
    w("[FINALE]")
    fin = [m for m in data["matches"] if m.get("phase") == "knockout" and m.get("round") == "Finale"]
    final_meta = meta.get("final", {})
    if fin and fin[0].get("status") == "played":
        m = fin[0]
        w(render_match_line(data, m, ""))
        render_match_events(data, m, w)
        champ = m["home"] if m["score"][0] > m["score"][1] else m["away"]
        w("Champion du Monde 2026 : " + champ)
    else:
        w("Aucun match joué")
        w("Date : {} | Lieu : {}, {}".format(
            final_meta.get("date", "N/D"), final_meta.get("venue", "N/D"),
            final_meta.get("city", "")))
        w("Champion du Monde 2026 : N/D")
    w("")

    # ── Classement buteurs ──
    w("[CLASSEMENT BUTEURS]")
    ranked, team_of, ogs = compute_top_scorers(data)
    if not ranked and not ogs:
        w("Aucun but marqué")
    else:
        rank = 0
        prev = None
        for i, (player, n) in enumerate(ranked, 1):
            if n != prev:
                rank = i
                prev = n
            w("{}. {} ({}) — {} but{}".format(
                rank, player, team_of.get(player, "?"), n, "s" if n > 1 else ""))
        for e in ogs:
            w("- {} c.s.c. ({}, contre son camp) — 1 but".format(
                e["player"], e.get("team", "?")))
    w("")

    # ── Statistiques par équipe ──
    w("[STATISTIQUES PAR ÉQUIPE]")
    w("")
    teams_sorted = sorted(data["teams"].keys(),
                          key=lambda t: (data["teams"][t].get("group", "Z"),
                                         data["teams"][t].get("seed", 9)))
    for team in teams_sorted:
        render_team_block(data, team, w)

    # ── NOUVEAU : Forme & dynamique ──
    w("[FORME ET DYNAMIQUE]")
    render_form_section(data, w)
    w("")

    # ── NOUVEAU : Engagement & enjeux ──
    w("[ENGAGEMENT ET ENJEUX]")
    render_engagement_section(data, w)
    w("")

    # ── NOUVEAU : Suspensions & disponibilités à venir ──
    w("[SUSPENSIONS ET DISPONIBILITÉS À VENIR]")
    render_avail_section(data, w)
    w("")

    # ── Analyse pronostic (agrégats calculés) ──
    w("[ANALYSE PRONOSTIC]")
    render_pronostic_section(data, gs, w)
    w("")

    w("=" * 75)
    w("FIN DU FICHIER — {} matchs enregistrés | {} équipes documentées | Dernière MAJ : {}".format(
        gs["matches"], len(data["teams"]), meta.get("last_updated", "N/D")))
    w("=" * 75)
    return "\n".join(L) + "\n"

def render_match_line(data, m, prefix):
    loc = m.get("venue", "TBD")
    if m.get("city"):
        loc += ", " + m["city"]
    if m.get("status") == "played":
        s = "{}{} {} - {} {} ({}, {})".format(
            prefix, m["home"], m["score"][0], m["score"][1], m["away"],
            m.get("date", "?"), loc)
        if m.get("et"):
            s += " [a.p.]"
        if m.get("pens"):
            s += " [Tab {}-{}]".format(m["pens"][0], m["pens"][1])
        return s
    suffix = m.get("sched_note", "à venir")
    return "{}{} - {} ({}, {}) — {}".format(
        prefix, m["home"], m["away"], m.get("date", "?"), loc, suffix)

TEAM_TO_CODE = {v: k for k, v in TEAM_CODES.items()}

def code_of(team):
    return TEAM_TO_CODE.get(team, team)

def fmt_minute(minute):
    if not minute:
        return ""
    s = str(minute)
    if "+" in s:
        base, extra = s.split("+", 1)
        return "{}'+{}".format(base, extra)
    return s + "'"

def fmt_event(e):
    parts = [p for p in [fmt_minute(e.get("minute")), code_of(e.get("team")), e.get("detail")] if p]
    return "{} ({})".format(e["player"], ", ".join(parts)) if parts else e["player"]

def render_match_events(data, m, w):
    evs = [e for e in data["events"] if e.get("match") == m.get("id")]
    goals = [e for e in evs if e.get("type") in ("goal", "pen", "own_goal")]
    yellows = [e for e in evs if e.get("type") == "yellow"]
    reds = [e for e in evs if e.get("type") == "red"]
    if goals:
        def gtxt(e):
            extra = []
            if e.get("type") == "pen":
                extra.append("pen.")
            if e.get("type") == "own_goal":
                extra.append("c.s.c.")
            if e.get("detail"):
                extra.append(e["detail"])
            inner = ", ".join([p for p in [fmt_minute(e.get("minute")), code_of(e.get("team"))] + extra if p])
            return "{} ({})".format(e["player"], inner)
        w("  Buteurs : " + ", ".join(gtxt(e) for e in goals))
    w("  Cartons jaunes : " + (", ".join(fmt_event(e) for e in yellows) if yellows else "aucun"))
    w("  Cartons rouges : " + (", ".join(fmt_event(e) for e in reds) if reds else "aucun"))
    tail = ""
    if m.get("attendance"):
        tail = "  Affluence : {}".format("{:,}".format(m["attendance"]).replace(",", " "))
    if m.get("note"):
        tail = (tail + " | Notes : " + m["note"]) if tail else "  Notes : " + m["note"]
    if tail:
        w(tail)

def render_standings_line(data, g):
    rows = compute_standings(data, g)
    parts = []
    for i, r in enumerate(rows, 1):
        gd = r["gd"]
        gds = "{:+d}".format(gd) if gd != 0 else "0"
        parts.append("{}. {} ({}pt, {})".format(i, r["team"], r["pts"], gds))
    return "Classement Groupe {} : ".format(g) + ", ".join(parts)

def render_team_block(data, team, w):
    info = data["teams"][team]
    rec = team_record(data, team)
    w("=== {} ===".format(team.upper()))
    if rec["pld"] == 0:
        w("Matchs joués : 0 | Bilan : 0V-0N-0D | Buts : 0 pour, 0 contre")
    else:
        w("Matchs joués : {} | Bilan : {}V-{}N-{}D | Buts : {} pour, {} contre".format(
            rec["pld"], rec["w"], rec["d"], rec["l"], rec["gf"], rec["ga"]))
    # buts
    cnt, og = scorers_for_team(data, team)
    bits = ["{} ({})".format(p, n) for p, n in cnt.items()]
    for e in og:
        bits.append("{} c.s.c. (1, par {})".format(e["player"], e.get("team", "?")))
    total = sum(cnt.values()) + len(og)
    w("Buts : " + (", ".join(bits) if bits else "aucun") + " | Total équipe : {}".format(total))
    # cartons
    yellows = team_events(data, team, "yellow")
    yc = OrderedDict()
    for e in yellows:
        yc.setdefault(e["player"], []).append(e)
    ytxt = ", ".join("{} ({}, vs {})".format(p, len(es), match_opp(data, es[0], team))
                     for p, es in yc.items())
    w("Cartons jaunes : " + (ytxt if ytxt else "aucun") + " | Total : {}".format(len(yellows)))
    reds = team_events(data, team, "red")
    rtxt = ", ".join("{} (vs {}{}{})".format(
        e["player"], match_opp(data, e, team),
        ", " + fmt_minute(e["minute"]) if e.get("minute") else "",
        ", " + e["detail"] if e.get("detail") else "") for e in reds)
    w("Cartons rouges : " + (rtxt if rtxt else "aucun") + " | Total : {}".format(len(reds)))
    # blessures
    injs = [x for x in data.get("injuries", []) if x.get("team") == team]
    if injs:
        itxt = ", ".join("{} ({}, sévérité:{}, statut:{}{})".format(
            x["player"], x.get("type", "?"), x.get("severity", "?"),
            x.get("status", "?"), ", " + x["note"] if x.get("note") else "")
            for x in injs)
        n_out = sum(1 for x in injs if x.get("status") == "out")
        w("Blessures : " + itxt + " | Joueurs indisponibles : {}".format(n_out))
    else:
        w("Blessures : aucune signalée | Joueurs indisponibles : 0")
    # compositions
    lus = [lu for lu in data.get("lineups", []) if lu.get("team") == team]
    lus.sort(key=lambda lu: lu.get("match", ""))
    if lus:
        w("Compositions alignées :")
        for lu in lus:
            mm = next((m for m in data["matches"] if m.get("id") == lu.get("match")), None)
            opp = opponent(mm, team) if mm else "?"
            date = mm.get("date", "?") if mm else "?"
            idx = lineup_index(data, team, lu.get("match"))
            w("  Match {} vs {} ({}) : {} — {}".format(
                idx, opp, date, lu.get("formation", "?"), lu.get("raw", "")))
            if lu.get("subs") or lu.get("coach"):
                subs = ", ".join(lu.get("subs", []))
                coach = lu.get("coach", "?")
                w("  Remplaçants disponibles : {} | Coach: {}".format(subs, coach))
        # formation la plus fréquente
        forms = defaultdict(int)
        for lu in lus:
            forms[lu.get("formation", "?")] += 1
        most = max(forms.items(), key=lambda kv: kv[1])[0]
        w("Composition la plus fréquente : " + most)
    else:
        w("Compositions alignées : aucune")
        w("Composition la plus fréquente : N/D")
    # joueurs clés
    kp = info.get("key_players", [])
    if kp:
        w("Joueurs clés : " + ", ".join(
            "{} ({})".format(k["name"], k.get("role", "")) +
            (" — " + k["note"] if k.get("note") else "") for k in kp))
    else:
        w("Joueurs clés : N/D")
    w("")

def match_opp(data, event, team):
    m = next((mm for mm in data["matches"] if mm.get("id") == event.get("match")), None)
    return opponent(m, team) if m else "?"

def lineup_index(data, team, match_id):
    ms = [m for m in team_matches_ordered(data, team) if m.get("status") == "played"]
    for i, m in enumerate(ms, 1):
        if m.get("id") == match_id:
            return i
    return 1

def render_form_section(data, w):
    notes = data.get("form_notes", [])
    pform = data.get("player_form", [])
    if not notes and not pform:
        # Forme calculée minimale depuis les résultats
        any_line = False
        for g in GROUPS:
            rows = compute_standings(data, g)
            played = [r for r in rows if r["pld"] > 0]
            if not played:
                continue
            for r in played:
                serie = "V" * r["w"] + "N" * r["d"] + "D" * r["l"]
                w("— {} : {} ({}pt, {} bal.)".format(r["team"], serie or "—", r["pts"], r["gd"]))
                any_line = True
        if not any_line:
            w("Aucune donnée de forme (compétition non commencée)")
        return
    for n in notes:
        trend = {"up": "↑", "down": "↓", "stable": "→"}.get(n.get("trend", ""), "")
        w("— {} {} : {}".format(n["team"], trend, n.get("note", "")))
    for p in pform:
        w("  · {} ({}) : {}".format(p["player"], p.get("team", "?"), p.get("note", "")))

def render_engagement_section(data, w):
    # Calcul : points + matchs restants par équipe, leader de groupe.
    any_line = False
    for g in GROUPS:
        rows = compute_standings(data, g)
        if not rows:
            continue
        total_group_matches = len([m for m in data["matches"] if m.get("group") == g])
        per_team = (total_group_matches // 2) if total_group_matches else 3
        played_any = any(r["pld"] > 0 for r in rows)
        if not played_any:
            continue
        leader = rows[0]
        w("— Groupe {} : leader {} ({}pt). Restant : {} journée(s).".format(
            g, leader["team"], leader["pts"], max(0, per_team - leader["pld"])))
        any_line = True
    # notes qualitatives d'engagement (collectées)
    for e in data.get("engagement_notes", []):
        w("  · {} : {}".format(e.get("team", "?"), e.get("note", "")))
        any_line = True
    if not any_line:
        w("Aucun enjeu calculable (phase de groupes non entamée)")

def render_avail_section(data, w):
    susp = compute_suspensions(data)
    if susp:
        w("— Suspendus au prochain match :")
        for s in susp:
            w("  · {} ({}) — {}".format(s["player"], s["team"], s["reason"]))
    else:
        w("— Suspendus au prochain match : aucun")
    # retours attendus
    returning = [x for x in data.get("injuries", []) if x.get("status") == "returning"]
    doubtful = [x for x in data.get("injuries", []) if x.get("status") == "doubtful"]
    if returning:
        w("— Retours attendus : " + ", ".join(
            "{} ({})".format(x["player"], x["team"]) for x in returning))
    if doubtful:
        w("— Incertains (doubtful) : " + ", ".join(
            "{} ({})".format(x["player"], x["team"]) for x in doubtful))
    # joueurs à 1 jaune
    risk = yellow_risk(data)
    if risk:
        w("— À 1 carton jaune (risque de suspension par cumul) :")
        for player, team, _ in risk:
            w("  · {} ({})".format(player, team))

def render_pronostic_section(data, gs, w):
    w("Données valides au : " + data["meta"].get("last_updated", "N/D"))
    w("")
    # mieux classés
    best = []
    inform = []
    clean = []
    offensive = []
    for g in GROUPS:
        for r in compute_standings(data, g):
            if r["pld"] == 0:
                continue
            if r["pts"] == 3 * r["pld"] and r["w"] == r["pld"]:
                best.append("{} (Gr.{})".format(r["team"], g))
            if r["w"] > 0:
                inform.append(r["team"])
            if r["ga"] == 0 and r["pld"] > 0:
                clean.append(r["team"])
            if r["gf"] >= 3 * r["pld"] and r["gf"] >= 3:
                offensive.append("{} ({} buts)".format(r["team"], r["gf"]))
    w("— Équipes avec 100% de victoires : " + (", ".join(best) if best else "aucune"))
    w("— Équipes en forme (au moins 1 victoire) : " + (", ".join(inform) if inform else "aucune"))
    w("— Solidité défensive (clean sheets) : " + (", ".join(clean) if clean else "aucune"))
    w("— Forces offensives (≥3 buts/match) : " + (", ".join(offensive) if offensive else "aucune"))
    w("")
    w("— Statistiques globales tournoi ({} matchs terminés) :".format(gs["matches"]))
    w("  Total buts : {} | Moyenne : {:.2f}/match".format(gs["goals"], gs["avg"]))
    w("  Cartons jaunes : {} | Cartons rouges : {}".format(gs["yellows"], gs["reds"]))
    if gs["att_total"]:
        w("  Affluence totale : {} | Moyenne : {}".format(
            "{:,}".format(gs["att_total"]).replace(",", " "),
            "{:,}".format(gs["att_avg"]).replace(",", " ")))
    w("")
    w("— Règles disciplinaires :")
    w("  2 cartons jaunes (matchs séparés) = 1 match de suspension")
    w("  Carton rouge direct = minimum 1 match de suspension")
    w("  Réinitialisation des avertissements : après la phase de groupes et après les quarts")

# ───────────────────────────── STATE ─────────────────────────────

def cmd_state():
    data = load()
    pm = played_matches(data)
    upcoming = sorted(
        [m for m in data["matches"] if m.get("status") != "played" and m.get("date")],
        key=lambda m: m["date"])[:8]
    out = {
        "last_updated": data["meta"].get("last_updated"),
        "current_phase": data["meta"].get("current_phase"),
        "played_match_ids": sorted(m["id"] for m in pm),
        "played_count": len(pm),
        "next_matches": [
            {"id": m["id"], "date": m.get("date"), "home": m.get("home"), "away": m.get("away")}
            for m in upcoming
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

# ───────────────────────────── MERGE ─────────────────────────────

def cmd_merge(delta_path):
    data = load()
    with open(delta_path, encoding="utf-8") as f:
        delta = json.load(f)

    stats = defaultdict(int)

    # meta
    if delta.get("meta"):
        for k, v in delta["meta"].items():
            data["meta"][k] = v

    # teams (upsert coach / key_players / group / seed)
    for team, info in (delta.get("teams") or {}).items():
        tgt = data["teams"].setdefault(team, {})
        for k, v in info.items():
            tgt[k] = v
        stats["teams"] += 1

    # matches (upsert par id ; matchs joués existants = immuables)
    by_id = {m["id"]: m for m in data["matches"]}
    for m in delta.get("matches", []):
        mid = m.get("id")
        if not mid:
            continue
        existing = by_id.get(mid)
        if existing and existing.get("status") == "played":
            stats["matches_skipped_immutable"] += 1
            continue
        if existing:
            existing.update(m)
            stats["matches_updated"] += 1
        else:
            data["matches"].append(m)
            by_id[mid] = m
            stats["matches_added"] += 1

    # events (dedup par match/player/minute/type ; minute vide/absente traitée pareil)
    def mkey(e):
        return (e.get("match"), e.get("player"), str(e.get("minute") or ""), e.get("type"))
    seen = {mkey(e) for e in data["events"]}
    for e in delta.get("events", []):
        key = mkey(e)
        if key in seen:
            continue
        data["events"].append(e)
        seen.add(key)
        stats["events_added"] += 1

    # lineups (upsert par match+team)
    lu_idx = {(lu.get("match"), lu.get("team")): i for i, lu in enumerate(data["lineups"])}
    for lu in delta.get("lineups", []):
        key = (lu.get("match"), lu.get("team"))
        if key in lu_idx:
            data["lineups"][lu_idx[key]] = lu
            stats["lineups_updated"] += 1
        else:
            data["lineups"].append(lu)
            lu_idx[key] = len(data["lineups"]) - 1
            stats["lineups_added"] += 1

    # injuries (upsert par team+player ; statut "resolved" => suppression)
    inj_idx = {(x.get("team"), x.get("player")): i for i, x in enumerate(data["injuries"])}
    for x in delta.get("injuries", []):
        key = (x.get("team"), x.get("player"))
        if x.get("status") == "resolved":
            if key in inj_idx:
                data["injuries"][inj_idx[key]] = None
                stats["injuries_resolved"] += 1
            continue
        if key in inj_idx and data["injuries"][inj_idx[key]] is not None:
            data["injuries"][inj_idx[key]] = x
            stats["injuries_updated"] += 1
        else:
            data["injuries"].append(x)
            inj_idx[key] = len(data["injuries"]) - 1
            stats["injuries_added"] += 1
    data["injuries"] = [x for x in data["injuries"] if x is not None]

    # form / engagement (remplacement par équipe)
    for field in ("form_notes", "player_form", "engagement_notes"):
        if field in delta:
            incoming = delta[field]
            teams_touched = {n.get("team") for n in incoming}
            kept = [n for n in data.get(field, []) if n.get("team") not in teams_touched]
            data[field] = kept + incoming
            stats[field] = len(incoming)

    save(data)
    txt = render(data)
    with open(TXT_PATH, "w", encoding="utf-8") as f:
        f.write(txt)
    print("Merge terminé :", dict(stats))
    print("Fichiers mis à jour : cdm2026.json + resultat_cdm2026.txt")

# ───────────────────────────── RENDER ────────────────────────────

def cmd_render():
    data = load()
    txt = render(data)
    with open(TXT_PATH, "w", encoding="utf-8") as f:
        f.write(txt)
    print("resultat_cdm2026.txt régénéré ({} octets)".format(len(txt.encode("utf-8"))))

# ─────────────────────────── BOOTSTRAP ───────────────────────────
# Parse l'ancien resultat_cdm2026.txt et reconstruit cdm2026.json (migration).

NAME_PAREN = re.compile(r'([^,(][^(]*?)\s*\(([^)]*)\)')
MINUTE_RE = re.compile(r"^\d+(?:'?\+?\d*)?'?$")

def parse_minute(tok):
    # gère "67'", "90'+2", "45'+5", "90+2"
    t = tok.strip().replace("'", "")
    return t if re.match(r"^\d+(\+\d+)?$", t) else None

def code_to_team(tok, fallback=None):
    tok = tok.strip()
    return TEAM_CODES.get(tok, fallback)

def parse_event_items(text):
    """Renvoie [(player, [tokens])] depuis une ligne 'A (x), B (y)'."""
    items = []
    for m in NAME_PAREN.finditer(text):
        name = m.group(1).strip().strip(",").strip()
        inner = [t.strip() for t in m.group(2).split(",")]
        items.append((name, inner))
    return items

def bootstrap(txt_path):
    with open(txt_path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    data = {
        "meta": {
            "tournament": "Coupe du Monde FIFA 2026",
            "last_updated": "2026-06-15T00:00:00Z",
            "current_phase": "Phase de groupes - Journée 1",
            "sources": ["FIFA.com", "Wikipédia", "BBC Sport", "ESPN"],
            "final": {"date": "2026-07-19", "venue": "MetLife Stadium",
                      "city": "East Rutherford, New Jersey"},
        },
        "teams": OrderedDict(),
        "matches": [],
        "events": [],
        "lineups": [],
        "injuries": [],
        "form_notes": [],
        "player_form": [],
        "engagement_notes": [],
    }

    # extraire l'en-tête (last_updated, phase) si présents
    for ln in lines[:8]:
        if ln.startswith("Dernière mise à jour :"):
            data["meta"]["last_updated"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("Phase actuelle :"):
            data["meta"]["current_phase"] = ln.split(":", 1)[1].strip()

    i = 0
    cur_group = None
    cur_match = None
    while i < len(lines):
        ln = lines[i]
        mg = re.match(r"\[PHASE DE GROUPES - GROUPE ([A-L])\]", ln)
        if mg:
            cur_group = mg.group(1)
            i += 1
            continue
        if ln.startswith("[") and not ln.startswith("[PHASE DE GROUPES"):
            cur_group = None  # on sort des groupes

        mm = re.match(r"^Match (\d+) : (.+)$", ln)
        if mm and cur_group:
            cur_match = parse_group_match(data, cur_group, int(mm.group(1)), mm.group(2))
            i += 1
            continue

        if cur_match and ln.startswith("  Buteurs :"):
            parse_goals(data, cur_match, ln.split(":", 1)[1])
            i += 1; continue
        if cur_match and ln.startswith("  Cartons jaunes :"):
            parse_cards(data, cur_match, ln.split(":", 1)[1], "yellow")
            i += 1; continue
        if cur_match and ln.startswith("  Cartons rouges :"):
            parse_cards(data, cur_match, ln.split(":", 1)[1], "red")
            i += 1; continue
        if cur_match and ln.startswith("  Affluence :"):
            rest = ln.split(":", 1)[1]
            if "| Notes :" in rest:
                aff, note = rest.split("| Notes :", 1)
                cur_match["attendance"] = num(aff)
                cur_match["note"] = note.strip()
            else:
                cur_match["attendance"] = num(rest)
            i += 1; continue
        if cur_match and ln.startswith("  Notes :"):
            cur_match["note"] = ln.split(":", 1)[1].strip()
            i += 1; continue

        mc = re.match(r"^Classement Groupe ([A-L]) : (.+)$", ln)
        if mc:
            assign_seeds(data, mc.group(1), mc.group(2))
            i += 1; continue

        mt = re.match(r"^=== (.+) ===$", ln)
        if mt:
            i = parse_team_block(data, mt.group(1), lines, i + 1)
            cur_match = None
            continue

        i += 1

    # garantir que toutes les équipes ont un groupe (depuis les matchs)
    save(data)
    return data

def parse_group_match(data, group, n, rest):
    """rest = 'Mexique 2 - 0 Afrique du Sud (2026-06-11, Estadio Azteca, Mexico City)' ou planifié."""
    mid = "{}{}".format(group, n)
    # séparer la partie parenthèses finale
    paren = ""
    pm = re.search(r"\(([^)]*)\)", rest)
    main = rest
    suffix = ""
    if pm:
        paren = pm.group(1)
        main = rest[:pm.start()].strip()
        suffix = rest[pm.end():].strip(" —")
    played = re.search(r" (\d+) - (\d+) ", " " + main + " ")
    parts = [p.strip() for p in paren.split(",")] if paren else []
    date = parts[0] if parts else None
    venue = parts[1] if len(parts) > 1 else None
    city = ", ".join(parts[2:]) if len(parts) > 2 else None
    match = {"id": mid, "phase": "group", "group": group, "matchday": 1,
             "date": date, "venue": venue, "city": city}
    score_m = re.match(r"^(.*?) (\d+) - (\d+) (.*)$", main)
    if score_m and "à venir" not in suffix and "en cours" not in suffix:
        match["home"] = score_m.group(1).strip()
        match["away"] = score_m.group(4).strip()
        match["score"] = [int(score_m.group(2)), int(score_m.group(3))]
        match["status"] = "played"
        match["et"] = False
        match["pens"] = None
    else:
        # planifié : 'Home - Away'
        teams = main.split(" - ")
        match["home"] = teams[0].strip()
        match["away"] = teams[1].strip() if len(teams) > 1 else "?"
        match["status"] = "scheduled"
        if suffix:
            match["sched_note"] = suffix
    register_team(data, match["home"], group)
    register_team(data, match["away"], group)
    data["matches"].append(match)
    return match

def register_team(data, team, group):
    if team and team not in data["teams"]:
        data["teams"][team] = {"group": group, "key_players": []}
    elif team and not data["teams"][team].get("group"):
        data["teams"][team]["group"] = group

def parse_goals(data, match, text):
    if "aucun" in text.lower():
        return
    home, away = match["home"], match["away"]
    sh, sa = match["score"]
    for name, inner in parse_event_items(text):
        minute = None
        team = None
        detail = None
        is_og = "OG" in name or any("c.s.c" in t for t in inner)
        is_pen = any("pen" in t.lower() for t in inner)
        nm = name.replace(" OG", "").strip()
        for t in inner:
            pm = parse_minute(t)
            # un token peut être "PAR c.s.c." → tester aussi le 1er mot comme code
            code = code_to_team(t) or code_to_team(t.split()[0] if t.split() else "")
            if pm and minute is None:
                minute = pm
            elif code:
                team = code
            elif "pen" not in t.lower() and "c.s.c" not in t and "OG" not in t:
                detail = t
        if team is None:
            # pas de code : attribuer à l'équipe qui a marqué
            team = home if sh > 0 and sa == 0 else (home if sh >= sa else away)
        ev = {"match": match["id"], "player": nm, "minute": minute, "team": team}
        if is_og:
            ev["type"] = "own_goal"
            ev["benefits"] = away if team == home else home
        elif is_pen:
            ev["type"] = "pen"
        else:
            ev["type"] = "goal"
        if detail and not is_og:
            ev["detail"] = detail
        data["events"].append(ev)

def parse_cards(data, match, text, ctype):
    if "aucun" in text.lower():
        return
    for name, inner in parse_event_items(text):
        minute = None
        team = None
        detail_parts = []
        for t in inner:
            pm = parse_minute(t)
            if pm and minute is None:
                minute = pm
            elif code_to_team(t):
                team = code_to_team(t)
            else:
                detail_parts.append(t)
        ev = {"match": match["id"], "player": name, "minute": minute,
              "team": team or "?", "type": ctype}
        if detail_parts:
            ev["detail"] = ", ".join(detail_parts)
        data["events"].append(ev)

def assign_seeds(data, group, text):
    order = re.findall(r"\d+\.\s*([^(]+?)\s*\(", text)
    for seed, name in enumerate(order, 1):
        name = name.strip()
        register_team(data, name, group)
        data["teams"][name]["seed"] = seed

def parse_team_block(data, team, lines, i):
    # Les en-têtes sont en MAJUSCULES → retrouver l'équipe déjà enregistrée.
    upper_map = {t.upper(): t for t in data["teams"]}
    team = upper_map.get(team.upper(), team)
    register_team(data, team, data["teams"].get(team, {}).get("group"))
    info = data["teams"][team]
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("=== ") or (ln.startswith("[") and "]" in ln):
            break
        if ln.startswith("Blessures :"):
            parse_injuries(data, team, ln.split(":", 1)[1])
        elif ln.startswith("  Match ") and " vs " in ln and ":" in ln:
            parse_lineup(data, team, ln)
        elif ln.startswith("  Remplaçants disponibles :"):
            attach_subs(data, team, ln.split(":", 1)[1])
        elif ln.startswith("Joueurs clés :"):
            parse_key_players(info, ln.split(":", 1)[1])
        i += 1
    return i

def parse_injuries(data, team, text):
    if "aucune" in text.lower():
        return
    main = text.split("| Joueurs indisponibles")[0]
    for name, inner in parse_event_items(main):
        typ = inner[0] if inner else "?"
        sev = None
        status = "out"
        note = None
        for t in inner[1:]:
            if t.startswith("severité:") or t.startswith("sévérité:"):
                sev = t.split(":", 1)[1]
            elif t.startswith("forfait:"):
                val = t.split(":", 1)[1]
                if val.lower().startswith("tous"):
                    status = "out"
                elif "doubtful" in val.lower():
                    status = "doubtful"
                    rest = val.split("—", 1)
                    if len(rest) > 1:
                        note = rest[1].strip()
                else:
                    note = val
            else:
                note = (note + ", " + t) if note else t
        inj = {"team": team, "player": name, "type": typ,
               "severity": sev or "?", "status": status}
        if note:
            inj["note"] = note
        data["injuries"].append(inj)

def parse_lineup(data, team, ln):
    body = ln.strip()[len("Match "):]
    m = re.match(r"(\d+) vs (.+?) \((\d{4}-\d{2}-\d{2})\) : (\S+) — (.+)$", body)
    if not m:
        return
    opp = m.group(2).strip()
    date = m.group(3)
    formation = m.group(4)
    raw = m.group(5).strip()
    # trouver le match correspondant
    match_id = None
    for mt in data["matches"]:
        if mt.get("date") == date and team in (mt.get("home"), mt.get("away")) \
           and opp in (mt.get("home"), mt.get("away")):
            match_id = mt["id"]
            break
    players = []
    for chunk in raw.split(";"):
        for p in chunk.split(","):
            p = p.strip()
            if p:
                players.append(p)
    data["lineups"].append({
        "match": match_id, "team": team, "formation": formation,
        "raw": raw, "players": players, "subs": [], "coach": None,
    })

def attach_subs(data, team, text):
    if "| Coach:" in text:
        subs_txt, coach = text.split("| Coach:", 1)
    else:
        subs_txt, coach = text, ""
    subs = [s.strip() for s in subs_txt.split(",") if s.strip()]
    # rattacher au dernier lineup de l'équipe
    for lu in reversed(data["lineups"]):
        if lu["team"] == team:
            lu["subs"] = subs
            lu["coach"] = coach.strip() or None
            break

def parse_key_players(info, text):
    kps = []
    for name, inner in parse_event_items(text):
        role = inner[0] if inner else ""
        note = ", ".join(inner[1:]) if len(inner) > 1 else None
        kp = {"name": name, "role": role}
        if note:
            kp["note"] = note
        kps.append(kp)
    info["key_players"] = kps

# ───────────────────────────── CLI ───────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "state":
        cmd_state()
    elif cmd == "render":
        cmd_render()
    elif cmd == "merge":
        if len(sys.argv) < 3:
            print("usage: cdm2026_tool.py merge <delta.json>"); sys.exit(1)
        cmd_merge(sys.argv[2])
    elif cmd == "bootstrap":
        src = sys.argv[2] if len(sys.argv) > 2 else LEGACY_TXT
        bootstrap(src)
        print("cdm2026.json reconstruit depuis", src)
    else:
        print("Commande inconnue:", cmd)
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
