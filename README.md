# 🎾 Shotgun Tennis — Jardin du Luxembourg

Automatise la capture des créneaux de tennis du week-end (10h–13h, sam & dim) au
Jardin du Luxembourg sur **AnyBuddy**, déclenchable **automatiquement** (à l'heure
d'ouverture pile) **et manuellement depuis ton iPhone**.

Quand un court se libère, tu reçois une **notification push** avec un bouton
**« Réserver maintenant »** : un tap ouvre AnyBuddy à la bonne date, tu n'as plus
qu'à **valider le paiement**. Le système ne paie pas à ta place et ne stocke pas ta carte.

---

## ⏰ D'abord, la règle d'ouverture (important)

Contrairement à ce qu'on croit souvent, sur AnyBuddy au Luxembourg un créneau
s'ouvre **exactement 7 jours avant, à la même heure** — pas « 5 jours avant, 1h plus tôt ».

| Créneau voulu | S'ouvre le |
|---|---|
| Samedi **10h00** | Le samedi précédent à **10h00** |
| Samedi **11h00** | Le samedi précédent à **11h00** |
| Dimanche **10h00** | Le dimanche précédent à **10h00** |

Bonne nouvelle : **tu n'as rien à calculer.** Le script lit l'heure d'ouverture
directement dans l'API d'AnyBuddy et se cale dessus à la seconde — même si la règle change.

> Les heures pleines (10h, 11h, 12h) ont **4 courts**, les demi-heures (10h30, 11h30) en ont **2**.
> Le script vise toute la fenêtre 10h→12h (un créneau d'1h démarrant à 12h finit à 13h).

---

## 🧩 Comment ça marche

```
   ┌─ Déclenchement AUTO (GitHub Actions, programmé sam/dim avant 10h/11h/12h)
   │
   ├─ Déclenchement MANUEL (bouton sur l'iPhone, quand tu veux)
   │
   ▼
shotgun.py  ──>  lit l'API AnyBuddy, attend l'ouverture, mitraille (plusieurs req/s)
   │
   ▼
Court libre détecté  ──>  notification PUSH sur ton téléphone (ntfy)
                              │
                              ▼
                     Tu tapes « Réserver »  ──>  AnyBuddy s'ouvre  ──>  tu paies ✅
```

---

## 📦 Les fichiers

- `shotgun.py` — le moteur (détection + notification). Testé sur l'API en direct.
- `.github/workflows/shotgun.yml` — le planificateur GitHub (auto + manuel).
- `README.md` — ce guide.

---

## 🚀 Installation (≈ 20 min, une seule fois)

### Étape 1 — Notifications sur le téléphone (ntfy) · 3 min

1. Installe l'appli **ntfy** (gratuite, sans compte) : [App Store](https://apps.apple.com/app/ntfy/id1625396347) / [Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy).
2. Invente un **nom de canal secret** et difficile à deviner, par ex.
   `lux-tennis-ambroise-7h3k9q`. **Garde-le privé** : quiconque le connaît verra tes notifs.
3. Dans l'appli ntfy : **+ → S'abonner à un sujet (topic)** → tape exactement ce nom.
4. Test rapide : sur ton ordi, lance
   ```bash
   python3 shotgun.py --test --topic "lux-tennis-ambroise-7h3k9q"
   ```
   Tu dois recevoir une notification « 🎾 Test shotgun » sur le téléphone. ✅

### Étape 2 — GitHub (le « moteur toujours allumé ») · 10 min

GitHub Actions exécute le script gratuitement, même téléphone et ordi éteints.

1. Crée un compte sur [github.com](https://github.com) si besoin.
2. Crée un **nouveau dépôt** (repository), par ex. `shotgun-tennis`.
   👉 Mets-le en **Public** : les minutes d'exécution sont alors **illimitées et gratuites**
   (tes secrets restent chiffrés et invisibles, même sur un repo public).
3. **Téléverse les fichiers** : bouton *Add file → Upload files*, dépose
   `shotgun.py` **et** le dossier `.github` (avec `workflows/shotgun.yml` dedans), puis *Commit*.
4. Ajoute ton canal ntfy comme **secret** :
   *Settings → Secrets and variables → Actions → New repository secret*
   - **Name** : `NTFY_TOPIC`
   - **Secret** : `wwwwwwwwwww` (ton nom de canal)
5. Active les workflows : onglet **Actions** → *I understand my workflows, go ahead and enable them*.

✅ **À partir d'ici, le déclenchement AUTOMATIQUE fonctionne déjà** : chaque samedi et
dimanche, juste avant 10h/11h/12h, le script se lance, attend l'ouverture et te notifie.

> Tu peux le **tester à la main tout de suite** : onglet *Actions → Shotgun Tennis
> Luxembourg → Run workflow → mode = now → Run*. Ça cherche un créneau immédiatement.

### Étape 3 — Le bouton sur l'iPhone (déclenchement manuel) · 7 min

Pour pouvoir lancer le shotgun **quand tu veux** depuis le téléphone (utile pour
chasser une annulation de dernière minute).

**3a. Créer un jeton GitHub (token)**
1. GitHub → *Settings* (de ton compte) → *Developer settings* → *Personal access tokens*
   → *Fine-grained tokens* → **Generate new token**.
2. *Repository access* → **Only select repositories** → choisis `shotgun-tennis`.
3. *Permissions* → *Repository permissions* → **Contents : Read and write**
   (suffisant pour déclencher un `repository_dispatch`).
4. Génère, **copie le token** (commence par `github_pat_…`). Tu ne le reverras plus.

**3b. Créer le raccourci (Shortcuts)**
1. Ouvre l'app **Raccourcis** → **+** (nouveau raccourci) → nomme-le « Shotgun Tennis ».
2. Ajoute l'action **« Obtenir le contenu de l'URL »** et règle :
   - **URL** :
     `https://api.github.com/repos/TON-PSEUDO/shotgun-tennis/dispatches`
     *(remplace `TON-PSEUDO` par ton identifiant GitHub)*
   - **Méthode** : `POST`
   - **En-têtes (Headers)** :
     - `Accept` : `application/vnd.github+json`
     - `Authorization` : `Bearer github_pat_…` *(ton token)*
   - **Corps de la requête** : `JSON` →
     ```json
     { "event_type": "shotgun", "client_payload": { "mode": "now" } }
     ```
3. Enregistre. Ajoute le raccourci à l'écran d'accueil (icône **Partager → Sur l'écran d'accueil**)
   pour avoir un **bouton d'un tap**.

Désormais : **un tap sur le bouton** → GitHub lance le script en mode `now` → s'il y a
un court libre, **notification immédiate**. Tu peux aussi mettre `"mode": "snipe"` pour
qu'il attende la prochaine ouverture.

---

## ⚙️ Réglages (facultatif)

Tout se règle en haut de `shotgun.py` ou via les variables d'environnement du workflow
(`.github/workflows/shotgun.yml`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `WINDOW_START` / `WINDOW_END` | `10:00` / `12:00` | fenêtre horaire visée (heure de début du créneau) |
| `TARGET_WEEKDAYS` | `5,6` | jours visés (5=sam, 6=dim ; ex. `5` pour samedi seul) |
| `CLUB_ID` | `tennis-jardin-du-luxembourg` | autre club AnyBuddy possible |
| `POLL_INTERVAL_MS` | `300` | fréquence de mitraillage (ms entre 2 requêtes) |
| `ADVANCE_DAYS` | `7` | jours d'avance d'ouverture (sert à viser la bonne date) |

Pour viser une autre fenêtre (ex. dimanche après-midi), change `WINDOW_START`/`END`
et ajuste les lignes `cron` du workflow (en **UTC** = heure de Paris − 2h l'été).

---

## ❗ Limites à connaître (honnêteté)

- **Ça ne « verrouille » pas le court.** Comme on s'arrête avant le paiement (choix
  volontaire : pas de carte stockée, risque de blocage de compte minimal), le créneau
  n'est à toi qu'**une fois payé**. Le système te fait gagner les secondes décisives
  (détection + notif + lien direct), mais il faut quand même **taper « Réserver » et
  payer vite**. Pour un week-end très prisé, garde l'app AnyBuddy déjà ouverte et connectée.
- **Automatiser ce type de réservation peut être contraire aux CGU d'AnyBuddy** et,
  poussé à l'extrême, faire suspendre ton compte. Reste raisonnable (pas de mitraillage
  permanent), c'est conçu pour quelques tirs ciblés le week-end.
- **Heure d'été/hiver** : les `cron` sont calés sur l'heure d'été. En hiver, le script
  attend simplement ~1h de plus tout seul. Mets le repo en **public** pour ne pas être
  limité en minutes Actions.
- Le lien de la notif ouvre la **page du club à la bonne date** ; il reste **un tap**
  pour choisir le court précis avant de payer. (Si un jour tu me donnes l'URL exacte
  d'un écran de paiement AnyBuddy, on pourra rapprocher encore le lien du bouton payer.)

---

## 🧪 Tester sans rien casser

```bash
python3 shotgun.py --test                       # vérifie API + horloge + notif
python3 shotgun.py --mode now                    # cherche un créneau tout de suite
python3 shotgun.py --mode now --date 2026-06-13  # teste une date précise
```
(Le mode `snipe` attend la vraie heure d'ouverture, donc il « patiente » si l'ouverture
n'est pas imminente — c'est normal.)
