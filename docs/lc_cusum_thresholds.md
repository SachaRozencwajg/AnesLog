# LC-CUSUM : Taux d'échec acceptables par geste technique

## Contexte

La méthode LC-CUSUM (Learning Curve – Cumulative Sum) est un test séquentiel
de Wald utilisé pour suivre objectivement l'acquisition de compétences
procédurales. Elle repose sur deux taux d'échec prédéfinis :

- **p0** (taux d'échec inacceptable) : hypothèse nulle — performance inadéquate
- **p1** (taux d'échec acceptable) : hypothèse alternative — performance adéquate

> **Convention littérature** : La convention la plus répandue est **p1 = 2 × p0**
> (le taux inacceptable est le double du taux acceptable).
> Paramètres d'erreur fixes : **α = 0.05** (erreur de type I), **β = 0.20** (erreur de type II).

> **⚠️ Note sur le code AnesLog** : Dans `compute_lc_cusum()`, le paramètre
> nommé `p0` correspond au taux inacceptable (hypothèse nulle) et `p1` au taux
> acceptable (hypothèse alternative). C'est cohérent avec le test de Wald mais
> inversé par rapport à certaines publications qui nomment `p0` le taux acceptable.

---

## Tableau récapitulatif

| Geste | p0 (inacceptable) | p1 (acceptable) | Seuil h | Justification | Source(s) |
|---|---|---|---|---|---|
| **KTA (Cathéter artériel)** | 0.20 | 0.10 | 2.773 | Taux de succès au premier essai ~71-80% pour les internes (palpation). Échec acceptable ~10% après formation. | [6,7] Sbmu.ac.ir 2023 ; NIH — étude radial art. résidents |
| **KTC (Cathéter veineux central)** | 0.20 | 0.10 | 2.773 | Taux de complications mécaniques 1.9-2.4% pour les seniors. Échec procédural (multiples ponctions, repositionnement) ~10-20% pour les internes. Consensus bloc péribulbaire : p0=0.20, p1=0.10. | [7,8] NIH — CVC complications résidents ; NIH — peribulbar CUSUM study |
| **Swan-Ganz** | 0.30 | 0.15 | 2.773 | Procédure complexe. Taux de complications 2-17%. Pas de CUSUM publié directement, mais la complexité justifie un taux plus élevé. Extrapolation du cathétérisme cardiaque. | [13-15] NIH — PAC complications ; WFSA tutorial |
| **Intubation double lumière** | 0.30 | 0.15 | 2.773 | Malpositionnement dans 33-50% des cas même chez les expérimentés. Plus difficile que l'intubation standard. ≥50 intubations standard pour 90% de succès, DLT requiert davantage. | [5-8] Medscape — DLT placement ; MDPI — DLT malpositioning |
| **Bloqueur bronchique** | 0.30 | 0.15 | 2.773 | Complexité similaire au DLT. Technique alternative nécessitant un fibroscope. Même ordre de difficulté. | Par analogie avec DLT |
| **Péridurale thoracique** | 0.20 | 0.10 | 2.773 | **Donnée directe LC-CUSUM** : p0=10% (taux acceptable) dans l'étude de Konrad et al. (2003), soit p0_Wald=0.20, p1_Wald=0.10. | [1] **Konrad et al., Anesth Analg 2003** — LC-CUSUM résidents AR, TEA p0=10% |
| **ALR para-sternale** | 0.20 | 0.10 | 2.773 | Bloc fascial écho-guidé. Taux d'échec des blocs nerveux ~6-11% pour les expérimentés. Courbe d'apprentissage ~10-15 procédures pour les blocs écho-guidés simples. | [5,8] NIH — US-guided nerve block failure 6.4% ; NIH — PNB overall 11% |
| **ALR périphérique (TAP block)** | 0.20 | 0.10 | 2.773 | Bloc de paroi, relativement simple techniquement. CUSUM : compétence après ~10 procédures. Taux d'échec attendu ~10%. | [1,5] Frontiers — US-CEB p0=0.20 ; NIH — trainee block failure 6.4% |
| **ALR périphérique (Sciatique poplité)** | 0.20 | 0.10 | 2.773 | Bloc périphérique écho-guidé classique. 90% de succès après 45 procédures (rachianesthésie comme proxy). Taux d'échec global PNB ~10%. | [6-8] BMJ — spinal/epidural learning ; Semantic Scholar — PNB variability |
| **ALR périphérique (Fémoral)** | 0.20 | 0.10 | 2.773 | Bloc périphérique écho-guidé standard. L'un des plus simples des blocs périphériques. Taux d'échec ~6-10%. | [5] NIH — US-guided nerve block failure 6.4% |
| **ETO peropératoire** | 0.30 | 0.15 | 2.773 | Procédure d'imagerie complexe. ASE/SCA recommandent ≥150 études pour la compétence spécialisée. CUSUM : acceptabilité variable, 10-20% selon la définition de l'échec. Interprétation + acquisition d'images. | [1,6-9] NIH — CUSUM TEE competency ; ASE guidelines |

---

## Détail des sources

### Source princière : Konrad et al. (2003)
> **Konrad C, et al.** "Learning manual skills in anesthesiology: Is there
> a recommended number of cases for anesthetic procedures?"
> *Anesthesia & Analgesia*, 2003; 96(6): 1781-1784.
> - Étude LC-CUSUM sur 18 résidents en anesthésie (rotation de 6 mois)
> - **Ponction trachéale** : taux d'échec acceptable = 1%
> - **Péridurale thoracique (TEA)** : taux d'échec acceptable = **10%**
> - **Intubation fibroscopique nasale (FONI)** : taux d'échec acceptable = **18%**
> - Résultat : une seule rotation de 6 mois est insuffisante pour atteindre
>   la compétence pour la plupart des procédures

### Rachianesthésie (proxy pour les blocs neuraxiaux)
> **Naik VN, et al.** — Fortune Journals
> - Rachianesthésie : compétent (p0=0.15) après médiane de 39 procédures
> - Proficient (p0=0.10) après moyenne de 67 procédures
> - Convention : p1 (inacceptable) = 2 × p0 (acceptable)

### Bloc caudal écho-guidé (proxy pour ALR écho-guidés)
> **Frontiers in Medicine** — Étude LC-CUSUM sur blocs caudaux écho-guidés
> - p0 = 0.20 (acceptable), p1 = 0.40 (inacceptable)
> - Compétence après 9-13 procédures selon le critère

### Péridurale lombaire
> **NIH** — Études multiples
> - Taux d'échec acceptables : 5-10% selon les études
> - Taux d'échec inacceptables : 10-30%
> - 90% de succès maintenu après ~60 procédures

### Intubation standard
> **NIH / OpenAirway** — Méta-analyse et études observationnelles
> - 90% de succès (10% d'échec) atteint après médiane de 57 intubations
> - 80% de succès après ~29-43 intubations selon la population
> - ACGME recommande minimum 35 tentatives

### Intubation fibroscopique
> **Konrad et al. (2003)** + **Signa Vitae**
> - FONI : taux d'échec acceptable = 18% (Konrad)
> - Intubation fibroscopique orotrachéale : p0 = 5% (Signa Vitae)
> - Compétence après ~15 procédures (80% succès)

### Blocs nerveux périphériques écho-guidés
> **NIH** — Études multiples
> - Taux d'échec global des PNB : ~6-11% pour les praticiens formés
> - Taux d'échec pour les internes : ~6.4% (blocs écho-guidés)
> - Compétence en visualisation d'aiguille : ~28 essais supervisés
> - Blocs continus : taux d'échec plus élevé (19-26% J1)

### ETO
> **NIH / ASE**
> - Pas de taux CUSUM standardisé pour l'ETO
> - ASE recommande ≥150 études pour la compétence spécialisée
> - Compétence de base après ~25 études supervisées
> - Taux d'échec variable selon la définition (acquisition vs interprétation)

### Swan-Ganz
> **NIH / WFSA**
> - Pas de CUSUM publié spécifiquement
> - Taux de complications : 2-17% (arythmies, ponction artérielle, etc.)
> - Rupture artère pulmonaire : 0.031-0.2%
> - Complexité justifie un taux d'échec acceptable plus élevé

### SFAR (France)
> **Société Française d'Anesthésie et de Réanimation**
> - Pas de taux d'échec CUSUM standardisés publiés par geste
> - Recommande la simulation et le suivi par auto-tests des acquis pratiques
> - Le référentiel de compétences (CFAR) liste les gestes sans seuils chiffrés
> - Les RPP (Recommandations de Pratiques Professionnelles) ne définissent pas
>   de taux d'échec acceptables pour l'apprentissage

---

## Implémentation dans AnesLog

Les valeurs `p0` et `p1` sont stockées en tant qu'attributs du modèle `Procedure`
et utilisées par `compute_lc_cusum()`. Pour les gestes sans données directes,
on applique la convention :
- Gestes simples (KTA, blocs périphériques) : **p0=0.20, p1=0.10**
- Gestes intermédiaires (KTC, péridurale, ALR) : **p0=0.20, p1=0.10**
- Gestes complexes (Swan-Ganz, DLT, bloqueur, ETO) : **p0=0.30, p1=0.15**

Le sénior peut ajuster ces valeurs dans la configuration de son équipe si besoin.
