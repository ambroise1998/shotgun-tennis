#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shotgun.py — Sniper de créneaux de tennis au Jardin du Luxembourg (AnyBuddy)
============================================================================

Ce que fait ce script :
  1. Il lit les disponibilités via l'API publique d'AnyBuddy (aucune authentification
     nécessaire pour LIRE) : https://api.anybuddyapp.com/v2/centers/{club}/availabilities
  2. Il lit l'heure d'OUVERTURE exacte des réservations renvoyée par l'API elle-même
     (champ "bookingRules"), donc il se cale automatiquement dessus, même si AnyBuddy
     change sa règle. (Règle constatée : ouverture 7 jours avant, à la même heure.)
  3. Il se synchronise sur l'horloge du serveur AnyBuddy (header HTTP "Date") pour ne
     pas dépendre de l'heure de la machine.
  4. À la seconde d'ouverture, il "mitraille" l'API (plusieurs requêtes par seconde)
     jusqu'à voir un court libre dans ta fenêtre (week-end, 10h-13h).
  5. Dès qu'un court se libère, il t'envoie une notification PUSH sur ton téléphone
     (via ntfy.sh) avec un bouton qui ouvre directement la page de réservation
     AnyBuddy à la bonne date -> tu n'as plus qu'à valider le paiement.

Le script ne paie PAS à ta place et ne stocke aucune carte : il t'amène en un tap
à l'écran de paiement, et c'est toi qui valides.

Usage :
  python3 shotgun.py --test                 # vérifie que tout marche (API + notif)
  python3 shotgun.py --mode now             # cherche tout de suite un créneau (déclenchement manuel)
  python3 shotgun.py --mode snipe           # attend l'ouverture puis mitraille (déclenchement auto)

Configuration : voir les variables ci-dessous ou les variables d'environnement
(pratique pour GitHub Actions). Tout est surchargé par les arguments en ligne de commande.
"""

import argparse
import base64
import datetime as dt
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

# ---------------------------------------------------------------------------
# CONFIGURATION (modifiable ici, par variable d'environnement, ou en argument)
# ---------------------------------------------------------------------------
CLUB_ID       = os.environ.get("CLUB_ID", "tennis-jardin-du-luxembourg")
ACTIVITY      = os.environ.get("ACTIVITY", "tennis")
SITE          = "https://www.anybuddyapp.com"
CLUB_URL      = SITE + "/fr/club/" + CLUB_ID  # page du club (?date=...)
API_BASE      = "https://api.anybuddyapp.com/v2/centers"


# Page de redirection (GitHub Pages) qui force l'ouverture dans Safari plutôt que
# dans l'appli. Si vide, la notif pointe directement vers AnyBuddy (ouvre l'appli).
REDIRECT_BASE = os.environ.get("REDIRECT_BASE", "")


def booking_url(date_str, slot):
    """Lien vers l'écran de réservation AVEC le créneau pré-sélectionné.
    Ex: .../fr/club/<club>/tennis?date=2026-06-11&serviceId=<id>&time=08%3A00&duration=60
    Si REDIRECT_BASE est défini, on enrobe l'URL dans la page de redirection
    (…/go.html#<url>) pour que ça s'ouvre dans Safari (web), pas dans l'appli."""
    direct = (f"{SITE}/fr/club/{CLUB_ID}/{ACTIVITY}"
              f"?date={date_str}"
              f"&serviceId={slot.get('service_id')}"
              f"&time={urllib.parse.quote(slot.get('time',''))}"
              f"&duration={slot.get('duration', 60)}")
    if REDIRECT_BASE:
        return f"{REDIRECT_BASE}#{urllib.parse.quote(direct, safe='')}"
    return direct

# Jours visés : 5 = samedi, 6 = dimanche (lundi=0 ... dimanche=6)
TARGET_WEEKDAYS = [int(x) for x in os.environ.get("TARGET_WEEKDAYS", "5,6").split(",")]

# Fenêtre horaire acceptée (heure de DÉBUT du créneau d'1h). 10:00 -> 12:00
# (un créneau qui démarre à 12:00 finit à 13:00). Format "HH:MM".
WINDOW_START  = os.environ.get("WINDOW_START", "10:00")
WINDOW_END    = os.environ.get("WINDOW_END", "12:00")

# Combien de jours à l'avance les créneaux s'ouvrent (AnyBuddy Luxembourg = 7).
# Sert seulement à viser la bonne date en mode "snipe" ; l'heure exacte est lue dans l'API.
ADVANCE_DAYS  = int(os.environ.get("ADVANCE_DAYS", "7"))

# ntfy : ton "canal" de notification. Mets une valeur secrète et difficile à deviner.
NTFY_TOPIC    = os.environ.get("NTFY_TOPIC", "")          # ex: "lux-tennis-ambroise-8x3k9"
NTFY_SERVER   = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

# Réglages du "mitraillage"
POLL_INTERVAL_MS  = int(os.environ.get("POLL_INTERVAL_MS", "300"))   # délai entre 2 requêtes
SNIPE_LEAD_MS     = int(os.environ.get("SNIPE_LEAD_MS", "800"))      # démarre N ms avant l'ouverture
MAX_SNIPE_SECONDS = int(os.environ.get("MAX_SNIPE_SECONDS", "120"))  # durée max de mitraillage
NOW_DURATION_SEC  = int(os.environ.get("NOW_DURATION_SEC", "20"))    # durée du mode "now"

PARIS_TZ = dt.timezone(dt.timedelta(hours=2))  # Europe/Paris en été (CEST, UTC+2)

# ---------------------------------------------------------------------------
# Outils bas niveau
# ---------------------------------------------------------------------------

def _hhmm_to_minutes(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)

WIN_START_MIN = _hhmm_to_minutes(WINDOW_START)
WIN_END_MIN   = _hhmm_to_minutes(WINDOW_END)


def http_get(url, timeout=10):
    """GET JSON + renvoie aussi le header Date du serveur (pour la synchro horloge)."""
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (shotgun-tennis)",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
        server_date = r.headers.get("Date")
    return json.loads(body), server_date


def availabilities_url(date_str, t_from="00:00", t_to="23:59"):
    qs = urllib.parse.urlencode({
        "activities": ACTIVITY,
        "date.from": f"{date_str}T{t_from}",
        "date.to":   f"{date_str}T{t_to}",
    })
    return f"{API_BASE}/{CLUB_ID}/availabilities?{qs}"


def fetch_day(date_str):
    """Renvoie (liste_de_créneaux_dans_la_fenêtre, bookingRules, server_date)."""
    data, server_date = http_get(availabilities_url(date_str, WINDOW_START, WINDOW_END))
    rules = data.get("bookingRules")
    slots = []
    for entry in data.get("data", []):
        start = entry.get("startDateTime")           # ex "2026-06-13T10:00"
        services = entry.get("services", [])
        if not services:
            continue
        try:
            hhmm = start.split("T")[1][:5]
            minutes = _hhmm_to_minutes(hhmm)
        except Exception:
            continue
        if WIN_START_MIN <= minutes <= WIN_END_MIN:
            slots.append({
                "start": start,
                "time": hhmm,
                "courts": len(services),
                "price_eur": services[0].get("price", 0) / 100.0,
                "service_id": services[0].get("id"),
                "slot_id": services[0].get("slotId"),
                "duration": services[0].get("duration", 60),
            })
    slots.sort(key=lambda s: s["time"])
    return slots, rules, server_date


def parse_opening_from_rules(rules):
    """
    Extrait la date/heure d'ouverture depuis le texte de l'API, ex:
    'Reservations open in 4 days ... (Jun 13, 2026 at 10:00).'
    Renvoie un datetime (Europe/Paris) ou None.
    """
    if not rules or "(" not in rules:
        return None
    try:
        inside = rules.split("(", 1)[1].split(")", 1)[0]   # "Jun 13, 2026 at 10:00"
        date_part, time_part = inside.split(" at ")
        when = dt.datetime.strptime(date_part.strip() + " " + time_part.strip(),
                                    "%b %d, %Y %H:%M")
        return when.replace(tzinfo=PARIS_TZ)
    except Exception:
        return None


def server_now(server_date_header):
    """Convertit le header HTTP 'Date' (GMT) en datetime Europe/Paris."""
    if not server_date_header:
        return dt.datetime.now(PARIS_TZ)
    t = dt.datetime.strptime(server_date_header, "%a, %d %b %Y %H:%M:%S %Z")
    return t.replace(tzinfo=dt.timezone.utc).astimezone(PARIS_TZ)


# ---------------------------------------------------------------------------
# Notification PUSH vers le téléphone (ntfy.sh)
# ---------------------------------------------------------------------------

_PRIORITY_MAP = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5, "max": 5}

def notify(title, message, click_url=None, priority="urgent", tags="tennis", actions=None):
    """Notification PUSH via ntfy.sh, au format JSON (gère l'unicode/emoji).
    `actions` = liste de (label, url) -> boutons « Réserver » (max 3)."""
    if not NTFY_TOPIC:
        print("  [notif] NTFY_TOPIC non défini -> notification ignorée (affichage local) :")
        print(f"  [notif] {title} | {message} | {click_url}")
        if actions:
            for lbl, u in actions:
                print(f"  [notif]   bouton: {lbl} -> {u}")
        return False
    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": _PRIORITY_MAP.get(priority, 5),
        "tags": [t.strip() for t in tags.split(",")] if tags else [],
    }
    if click_url:
        payload["click"] = click_url           # tap sur le corps de la notif -> ouvre le lien
    if actions:
        payload["actions"] = [
            {"action": "view", "label": lbl, "url": u, "clear": True}
            for (lbl, u) in actions[:3]
        ]
    elif click_url:
        payload["actions"] = [{
            "action": "view", "label": "Réserver maintenant",
            "url": click_url, "clear": True,
        }]
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(NTFY_SERVER, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        print(f"  [notif] envoyée ✔  ({title})")
        return True
    except Exception as e:
        print(f"  [notif] échec: {e}")
        return False


# ---------------------------------------------------------------------------
# Logique de dates
# ---------------------------------------------------------------------------

def next_target_dates(reference, advance_days, weekdays, horizon=14):
    """
    Pour le mode 'now' : prochaines dates jouables (sam/dim) dans les 'horizon' jours,
    qui sont DÉJÀ ouvertes à la réservation (donc à <= advance_days de distance).
    """
    out = []
    for d in range(0, horizon + 1):
        day = (reference + dt.timedelta(days=d)).date()
        if day.weekday() in weekdays and d <= advance_days:
            out.append(day.isoformat())
    return out


def snipe_play_date(reference, advance_days, weekdays):
    """
    Pour le mode 'snipe' : la date jouable qui s'ouvre AUJOURD'HUI = reference + advance_days,
    si ce jour-là est un jour visé.
    """
    day = (reference + dt.timedelta(days=advance_days)).date()
    if day.weekday() in weekdays:
        return day.isoformat()
    # sinon, prochaine date visée qui s'ouvrira
    for d in range(advance_days, advance_days + 8):
        day = (reference + dt.timedelta(days=d)).date()
        if day.weekday() in weekdays:
            return day.isoformat()
    return None


def announce(date_str, slots):
    best = slots[0]
    n = sum(s["courts"] for s in slots)
    title = f"🎾 Court libre {date_str} {best['time']} !"
    times = ", ".join(f"{s['time']} ({s['courts']} court{'s' if s['courts']>1 else ''})"
                      for s in slots)
    msg = (f"{CLUB_ID} — {date_str}\n"
           f"Dispo : {times}\n"
           f"Prix : {best['price_eur']:.0f}€ / court\n"
           f"➡️ Tape un horaire pour aller direct au paiement.")
    # un bouton par horaire dispo (max 3) -> lien PRÉCIS vers le paiement
    actions = [(f"Réserver {s['time']}", booking_url(date_str, s)) for s in slots[:3]]
    click = booking_url(date_str, best)
    notify(title, msg, click_url=click, actions=actions)
    print(f"  >>> {title}")
    print(f"      {times}  | total {n} court(s)")
    for lbl, u in actions:
        print(f"      [{lbl}] {u}")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def mode_now():
    """Vérifie tout de suite la dispo (déclenchement manuel / chasse aux annulations)."""
    _, server_date = http_get(availabilities_url(
        (dt.datetime.now(PARIS_TZ)).date().isoformat(), WINDOW_START, WINDOW_END))
    now = server_now(server_date)
    dates = next_target_dates(now, ADVANCE_DAYS, TARGET_WEEKDAYS)
    print(f"[now] {now:%Y-%m-%d %H:%M:%S} — je vérifie : {dates}")
    deadline = time.time() + NOW_DURATION_SEC
    found = False
    while time.time() < deadline and not found:
        for date_str in dates:
            try:
                slots, rules, _ = fetch_day(date_str)
            except Exception as e:
                print(f"  {date_str}: erreur {e}")
                continue
            if slots:
                announce(date_str, slots)
                found = True
                break
            else:
                print(f"  {date_str}: rien ({rules or 'complet'})")
        if not found:
            time.sleep(max(POLL_INTERVAL_MS, 1500) / 1000.0)
    if not found:
        print("[now] Aucun créneau libre pour l'instant.")
    return found


def mode_snipe():
    """Attend l'ouverture exacte (lue dans l'API) puis mitraille."""
    now0 = dt.datetime.now(PARIS_TZ)
    date_str = snipe_play_date(now0, ADVANCE_DAYS, TARGET_WEEKDAYS)
    if not date_str:
        print("[snipe] Aucune date cible à viser aujourd'hui.")
        return False
    print(f"[snipe] Date jouable visée : {date_str} (fenêtre {WINDOW_START}-{WINDOW_END})")

    # 1) lire l'heure d'ouverture annoncée par l'API
    slots, rules, server_date = fetch_day(date_str)
    if slots:
        print("[snipe] Des créneaux sont DÉJÀ ouverts — je notifie tout de suite.")
        announce(date_str, slots)
        return True
    opening = parse_opening_from_rules(rules)
    now = server_now(server_date)
    if opening is None:
        print(f"[snipe] Heure d'ouverture introuvable dans l'API (rules={rules!r}).")
        print("        Je mitraille quand même pendant la durée max.")
        target = now
    else:
        print(f"[snipe] Ouverture annoncée par l'API : {opening:%Y-%m-%d %H:%M:%S} "
              f"(heure serveur actuelle : {now:%H:%M:%S})")
        target = opening

    # 2) attendre jusqu'à SNIPE_LEAD_MS avant l'ouverture.
    #    On se base sur l'horloge SERVEUR (estimée via l'offset machine/serveur) pour
    #    ne pas dépendre de l'heure locale de la machine.
    _SRV_OFFSET["value"] = (now - dt.datetime.now(PARIS_TZ)).total_seconds()
    while True:
        left = (target - server_now_estimate(date_str)).total_seconds() - SNIPE_LEAD_MS / 1000.0
        if left <= 0:
            break
        if left > 90:
            # longue attente : dors gros, puis on resynchronisera l'horloge serveur
            _SRV_OFFSET["value"] = None   # force une resynchro au prochain estimate()
            print(f"[snipe] Attente {left:.0f}s avant l'ouverture…")
            time.sleep(min(left - 30, 300))
        else:
            time.sleep(min(left, 2))

    # 3) mitraillage
    print(f"[snipe] 🔫 Mitraillage ! (toutes les {POLL_INTERVAL_MS} ms, max {MAX_SNIPE_SECONDS}s)")
    deadline = time.time() + MAX_SNIPE_SECONDS
    tries = 0
    while time.time() < deadline:
        tries += 1
        try:
            slots, _, _ = fetch_day(date_str)
        except Exception as e:
            slots = []
        if slots:
            print(f"[snipe] Trouvé après {tries} requêtes.")
            announce(date_str, slots)
            return True
        time.sleep(POLL_INTERVAL_MS / 1000.0)
    print(f"[snipe] Rien trouvé après {tries} requêtes. (Tout est parti, ou ouverture décalée.)")
    notify("🎾 Shotgun : raté",
           f"Aucun court 10-13h capté pour le {date_str} après {tries} essais.",
           priority="default", tags="warning")
    return False


# petite aide : estimation de l'heure serveur sans refaire un appel à chaque boucle
_SRV_OFFSET = {"value": None}
def server_now_estimate(date_str):
    if _SRV_OFFSET["value"] is None:
        try:
            _, _, sd = http_get(availabilities_url(date_str, WINDOW_START, WINDOW_END))
            _SRV_OFFSET["value"] = (server_now(sd) - dt.datetime.now(PARIS_TZ)).total_seconds()
        except Exception:
            _SRV_OFFSET["value"] = 0.0
    return dt.datetime.now(PARIS_TZ) + dt.timedelta(seconds=_SRV_OFFSET["value"])


def mode_test():
    print("=== TEST ===")
    today = dt.datetime.now(PARIS_TZ)
    print(f"Heure machine (Paris) : {today:%Y-%m-%d %H:%M:%S}")
    # 1) API joignable + horloge serveur
    probe_date = (today + dt.timedelta(days=ADVANCE_DAYS)).date().isoformat()
    try:
        slots, rules, sd = fetch_day(probe_date)
        print(f"API OK. Date sonde {probe_date} -> {len(slots)} créneau(x) dans la fenêtre. "
              f"bookingRules={rules!r}")
        print(f"Horloge serveur AnyBuddy : {server_now(sd):%Y-%m-%d %H:%M:%S}")
        op = parse_opening_from_rules(rules)
        if op:
            print(f"Heure d'ouverture détectée : {op:%Y-%m-%d %H:%M:%S}")
    except Exception as e:
        print(f"ERREUR API : {e}")
        return
    # 2) dates cibles
    print(f"Mode 'now' viserait : {next_target_dates(today, ADVANCE_DAYS, TARGET_WEEKDAYS)}")
    print(f"Mode 'snipe' viserait : {snipe_play_date(today, ADVANCE_DAYS, TARGET_WEEKDAYS)}")
    # 3) notif de test
    print(f"NTFY_TOPIC = {NTFY_TOPIC or '(non défini)'}")
    notify("🎾 Test shotgun", "Si tu vois cette notif, le push fonctionne ✔",
           click_url=f"{CLUB_URL}", priority="default")
    print("=== FIN TEST ===")


def main():
    ap = argparse.ArgumentParser(description="Sniper de créneaux tennis AnyBuddy")
    ap.add_argument("--mode", choices=["snipe", "now", "test"], default="snipe")
    ap.add_argument("--test", action="store_true", help="raccourci pour --mode test")
    ap.add_argument("--topic", help="surcharge NTFY_TOPIC")
    ap.add_argument("--date", help="force une date jouable AAAA-MM-JJ (mode now)")
    args = ap.parse_args()

    global NTFY_TOPIC
    if args.topic:
        NTFY_TOPIC = args.topic

    mode = "test" if args.test else args.mode
    if mode == "test":
        mode_test()
    elif mode == "now":
        if args.date:
            slots, rules, _ = fetch_day(args.date)
            if slots:
                announce(args.date, slots)
            else:
                print(f"{args.date}: rien ({rules or 'complet'})")
        else:
            mode_now()
    else:
        mode_snipe()


if __name__ == "__main__":
    main()
