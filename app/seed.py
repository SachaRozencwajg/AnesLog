"""
Database seeding script.
Run with:  python -m app.seed

===========================================================================
HOW TO ADD NEW PROCEDURES:
Just add entries to the SEED_DATA dictionary below.
The key is the category name (French), the value is a list of procedure names.
===========================================================================
"""
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone, date
from app.database import engine, SessionLocal, Base
from app.models import (
    User, Category, Procedure, ProcedureLog, UserRole, Team, AutonomyLevel,
    ComplicationRole, CompetencyDomain, Competency, DesarPhase, Semester,
    GuardLog, GuardType, ProcedureCompetence, CaseType,
)
from app.auth import hash_password

# ---------------------------------------------------------------------------
# DESAR Competency Domains (Journal Officiel, 28 avril 2017)
# ---------------------------------------------------------------------------
COMPETENCY_DOMAINS = [
    {"code": "A", "name": "Évaluation pré-opératoire",
     "description": "Examen pré-op, classification de risque, allergie, jeûne, prémédication",
     "phase_required": DesarPhase.socle, "display_order": 1},
    {"code": "B", "name": "Anesthésie générale",
     "description": "Check-list, voies aériennes, monitorage, induction, ventilation, hypothermie",
     "phase_required": DesarPhase.socle, "display_order": 2},
    {"code": "C", "name": "Réveil et SSPI",
     "description": "SSPI, NVPO, complications post-opératoires immédiates",
     "phase_required": DesarPhase.socle, "display_order": 3},
    {"code": "D", "name": "Anesthésie locorégionale",
     "description": "Pharmacologie AL, rachianesthésie, péridurale, blocs périphériques",
     "phase_required": DesarPhase.socle, "display_order": 4},
    {"code": "E", "name": "Douleur péri-opératoire",
     "description": "Morphiniques, analgésie multimodale, douleur chronique",
     "phase_required": DesarPhase.approfondissement, "display_order": 5},
    {"code": "F", "name": "Terrain & chirurgie spécialisée",
     "description": "F.a Respiratoire, F.b Cardiovasculaire, F.c Neuro, F.d Métabolisme, F.e Hémostase, F.f Obstétrique, F.g Pédiatrie, F.h Céphalique, F.i Dig/uro/ortho, F.j Hors bloc",
     "phase_required": DesarPhase.approfondissement, "display_order": 6},
    {"code": "G", "name": "Échographie",
     "description": "ETT, écho pleuropulmonaire, abdominale, vasculaire, doppler transcrânien, ALR écho-guidée",
     "phase_required": DesarPhase.socle, "display_order": 7},
    {"code": "COBA", "name": "CoBaTrICE (Réanimation)",
     "description": "Compétences de réanimation communes avec le MIR : défaillances d'organes, sepsis, techniques lourdes, éthique",
     "phase_required": DesarPhase.socle, "display_order": 8},
]

# ---------------------------------------------------------------------------
# Competencies within each domain (~30 loggable competencies)
# ---------------------------------------------------------------------------
COMPETENCIES = {
    # ── Domain A ─────────────────────────────────────────────────────
    # Évaluer le risque opératoire, présenter une prémédication,
    # préparer le patient à l'opération et l'informer
    "A": [
        {"name": "Examen pré-opératoire", "description": "Évaluation complète du patient avant intervention"},
        {"name": "Classification de risque opératoire", "description": "ASA, scores de risque (Lee, Apfel)"},
        {"name": "Risque allergique", "description": "Dépistage, bilan allergologique, prévention"},
        {"name": "Examens complémentaires et gestion péri-opératoire des médicaments", "description": "Stratégie anesthésique, gestion des anticoagulants"},
        {"name": "Règles du jeûne préopératoire", "description": "Adulte et enfant, prémédication"},
    ],
    # ── Domain B ─────────────────────────────────────────────────────
    # Conduire une anesthésie générale
    "B": [
        {"name": "Vérifications et procédures de contrôle", "description": "Check-list avant acte interventionnel sous anesthésie"},
        {"name": "Contrôle des voies aériennes", "description": "IOT, intubation difficile, masque laryngé, algorithme ID"},
        {"name": "Appareils d'anesthésie", "description": "Vérification, principes de fonctionnement, modes de ventilation, panne"},
        {"name": "Posture et installation du patient", "description": "Surveillance, complications positionnelles"},
        {"name": "Surveillance d'une anesthésie", "description": "Profondeur de l'anesthésie, BIS, signes cliniques"},
        {"name": "Monitorage de base en anesthésie", "description": "SpO2, capnométrie, ECG, PA"},
        {"name": "Différents types d'induction", "description": "En urgence, en l'absence de voie veineuse, inhalatoire"},
        {"name": "Besoins liquidiens per-opératoires", "description": "Remplissage, solutés, objectifs hémodynamiques"},
        {"name": "Hypothermie", "description": "Prévention, moyens de réchauffement, conséquences"},
    ],
    # ── Domain C ─────────────────────────────────────────────────────
    # Conduire le réveil de l'anesthésie
    "C": [
        {"name": "Physiopathologie du réveil", "description": "Surveillance, incidents-accidents, score d'Aldrete"},
        {"name": "Nausées et vomissements post-opératoires", "description": "Prévention et traitement des NVPO"},
    ],
    # ── Domain D ─────────────────────────────────────────────────────
    # Pratiquer une anesthésie loco-régionale
    "D": [
        {"name": "Pharmacologie des anesthésiques locaux", "description": "Toxicité des AL, doses maximales, intralipides"},
        {"name": "Techniques d'ALR", "description": "Rachidienne, péridurale, caudale, blocs périphériques"},
        {"name": "Gestion des complications de l'ALR", "description": "Rachianesthésie totale, toxicité systémique, hématome"},
    ],
    # ── Domain E ─────────────────────────────────────────────────────
    # Gérer la douleur pendant et dans les suites d'une opération
    "E": [
        {"name": "Morphiniques et antagonistes", "description": "Utilisation et prescription, PCA"},
        {"name": "Antalgiques non morphiniques", "description": "Paracétamol, AINS, néfopam, kétamine"},
        {"name": "Anti-hyperalgésiques", "description": "Prévention de l'hyperalgésie, kétamine, gabapentinoïdes"},
        {"name": "Évaluation de la douleur", "description": "Échelles, douleur post-opératoire, physiopathologie"},
        {"name": "Monitorage de l'analgésie", "description": "ANI, pupillométrie, indices nociceptifs"},
        {"name": "Douleur chronique", "description": "Chronification, prise en charge multidisciplinaire"},
    ],
    # ── Domain F ─────────────────────────────────────────────────────
    # Tenir compte des répercussions de l'anesthésie sur les grandes
    # fonctions ; adapter la stratégie au terrain et au type de chirurgie
    "F": [
        {"name": "F.a — Fonction respiratoire", "description": "Insuffisant respiratoire, asthme, chirurgie thoracique, thoracoscopie, œsophage"},
        {"name": "F.b — Fonction cardiovasculaire", "description": "Coronarien, troubles du rythme, IC, HTA, chirurgie cardiaque et vasculaire"},
        {"name": "F.c — Neuro-anesthésie", "description": "PIC, traumatisme crânien, tumeur intracrânienne, mort encéphalique"},
        {"name": "F.d — Rein et anesthésie", "description": "Fonction rénale, EER, transplantation rénale, chirurgie urologique"},
        {"name": "F.e — Hémostase et anesthésie", "description": "Troubles de l'hémostase, transfusion, épargne sanguine"},
        {"name": "F.f — Obstétrique", "description": "Césarienne, ALR obstétricale, toxémie, hémorragie de la délivrance"},
        {"name": "F.g — Pédiatrie", "description": "Voies aériennes, apports hydro-électrolytiques, urgences digestives, ALR pédiatrique"},
        {"name": "F.h — Chirurgie céphalique", "description": "ORL, ophtalmologie, maxillo-faciale, laser, endoscopies"},
        {"name": "F.i — Chirurgie digestive/uro/ortho", "description": "Hanche, genou, lambeaux, occlusions, chirurgie hépatique, prostate"},
        {"name": "F.j — Hors bloc opératoire", "description": "Endoscopies digestives, radiologie interventionnelle, neuroradiologie"},
    ],
    # ── Domain G ─────────────────────────────────────────────────────
    # Utiliser les ultrasons en anesthésie-réanimation
    "G": [
        {"name": "Échocardiographie cardiaque", "description": "Fonction contractile, épanchement péricardique, conditions de charge"},
        {"name": "Échographie pleuro-pulmonaire", "description": "Épanchement pleural, qualité et quantité"},
        {"name": "Échographie abdominale", "description": "Épanchement liquidien, globe vésical"},
        {"name": "Échographie vasculaire", "description": "Reconnaissance des vaisseaux, guidage de ponction"},
    ],
    # ── CoBaTrICE (Réanimation) ──────────────────────────────────────
    # Compétences communes avec le MIR (Journal Officiel 28 avril 2017)
    "COBA": [
        {"name": "Approche structurée du patient grave", "description": "Identification, évaluation et traitement des défaillances viscérales"},
        {"name": "Monitorage et examens complémentaires", "description": "Évaluer, monitorer, prescrire et interpréter les données"},
        {"name": "Défaillance rénale", "description": "Identification et prise en charge"},
        {"name": "Défaillance neurologique", "description": "Identification et prise en charge"},
        {"name": "Défaillance cardiocirculatoire", "description": "État de choc, catécholamines, monitorage"},
        {"name": "Défaillance pulmonaire", "description": "SDRA, ventilation protectrice"},
        {"name": "Défaillance hépato-digestive", "description": "Insuffisance hépatique, hémorragie digestive"},
        {"name": "Défaillance hématologique", "description": "CIVD, thrombopénie, transfusion"},
        {"name": "Sepsis et antibiothérapie", "description": "Identification, Surviving Sepsis Campaign"},
        {"name": "Intoxications", "description": "Médicamenteuses et toxines environnementales"},
        {"name": "Complications du péripartum", "description": "Mise en danger de la vie de la mère"},
        {"name": "Antibiothérapie en réanimation", "description": "Spécificités, pharmacocinétique"},
        {"name": "Produits sanguins labiles", "description": "Administration en toute sécurité"},
        {"name": "Remplissage et vasopresseurs", "description": "Solutés, médicaments vasomoteurs et inotropes"},
        {"name": "Assistance circulatoire mécanique", "description": "ECMO, contre-pulsion, Impella"},
        {"name": "Ventilation invasive", "description": "Intubation, réglages ventilatoires, sevrage"},
        {"name": "Ventilation non invasive", "description": "VNI, OHD, CPAP"},
        {"name": "Épuration extra-rénale", "description": "Hémodialyse, hémofiltration continue, sevrage"},
        {"name": "Troubles hydro-électrolytiques", "description": "Glucose, équilibre acido-basique"},
        {"name": "Nutrition en réanimation", "description": "Évaluation et mise en œuvre"},
        {"name": "Patient chirurgical à haut risque", "description": "Soins péri-opératoires, chirurgie cardiaque et neurochirurgie"},
        {"name": "Transplantation d'organes", "description": "Soins du patient transplanté"},
        {"name": "Patient traumatisé", "description": "Soins pré et postopératoires"},
        {"name": "Conséquences physiques et psychologiques", "description": "Minimiser l'impact sur patients et familles"},
        {"name": "Soins de fin de vie et limitation thérapeutique", "description": "Éthique, entretien avec familles, collaboration multidisciplinaire"},
        {"name": "Arrêt cardiaque récent", "description": "Gestion et réanimation cardio-pulmonaire"},
        {"name": "Urgences vitales et procédures de secours", "description": "Prise en charge immédiate"},
        {"name": "Sédation et analgésie en réanimation", "description": "Évaluation, prévention du délire, curarisation"},
        {"name": "Transport du patient critique", "description": "Transport sécurisé en dehors de l'unité"},
        {"name": "Gestion d'afflux de victimes", "description": "Accidents à nombreuses victimes, plan blanc"},
    ],
}

# ---------------------------------------------------------------------------
# Existing procedure → competency domain mapping (default tagging)
# Maps procedure names to competency domain codes
# ---------------------------------------------------------------------------
PROCEDURE_COMPETENCY_MAP = {
    # Chirurgie Thoracique → F (F.a)
    "Résection pulmonaire": "F",
    "CPC": "F",
    "Bronchoscopie (EBUS)": "F",
    "Bronchoscopie rigide": "F",
    "Transplantation pulmonaire": "F",
    # Chirurgie Cardiaque → F (F.b)
    "PAC sous CEC": "F",
    "PAC à cœur battant": "F",
    "Remplacement valvulaire aortique (RVAo)": "F",
    "Remplacement valvulaire mitral (RVM/plastie)": "F",
    "Aorte ascendante (TSC, Bentall, Tiron David)": "F",
    "Transplantation cardiaque": "F",
    "Assistances ventriculaires (LVAD/RVAD)": "F",
    # Chirurgie Vasculaire → F (F.b)
    "Aorte descendante (AAA)": "F",
    "Endoprothèse aortique": "F",
    "TAVI": "F",
    # Gestes techniques
    "KTA (Cathéter artériel)": "B",
    "KTC (Cathéter veineux central)": "B",
    "Swan-Ganz (Cathéter artériel pulmonaire)": "B",
    "Intubation double lumière": "B",
    "Bloqueur bronchique": "B",
    "Péridurale thoracique": "D",
    "ALR para-sternale": "D",
    "ALR périphérique (TAP block)": "D",
    "ALR périphérique (Sciatique poplité)": "D",
    "ALR périphérique (Fémoral)": "D",
    "ETO peropératoire": "G",
    # Complications
    "Choc hémorragique": "COBA",
    "Choc cardiogénique": "COBA",
    "Tamponnade": "COBA",
    "ACR (Arrêt cardio-respiratoire)": "COBA",
    "Choc septique": "COBA",
    "SDRA": "COBA",
    "Révision pour hémostase": "F",
    "Insuffisance rénale aiguë (dialyse)": "COBA",
    "AVC périopératoire": "COBA",
    # Consultations d'anesthésie → A
    "Consultation pré-opératoire": "A",
    "Visite pré-anesthésique": "A",
    # Pathologies de réanimation → COBA
    "Choc septique (réa)": "COBA",
    "SDRA (réa)": "COBA",
    "Choc cardiogénique (réa)": "COBA",
    "Choc hémorragique (réa)": "COBA",
    "Insuffisance rénale aiguë (réa)": "COBA",
    "Intoxication médicamenteuse": "COBA",
    "État de mal épileptique": "COBA",
    "Polytraumatisme": "COBA",
    "Hémorragie du post-partum": "COBA",
    "Arrêt cardiaque (réa)": "COBA",
    "Transplantation (réa)": "COBA",
    "Mort encéphalique (réa)": "COBA",
}

# ---------------------------------------------------------------------------
# Surgery types (maps to F.a-F.j sub-domains)
# ---------------------------------------------------------------------------
SURGERY_TYPES = [
    "Thoracique", "Cardiovasculaire", "Vasculaire", "Neurochirurgie",
    "Obstétrique", "Pédiatrie", "ORL/Ophta", "Digestive", "Urologie",
    "Orthopédie", "Hors bloc",
]

# ---------------------------------------------------------------------------
# Seed data – edit this dict to add/remove categories and procedures
# ---------------------------------------------------------------------------
# Map category names to their correct section
CATEGORY_SECTIONS: dict[str, str] = {
    "Gestes techniques": "gesture",
    "Complications post-opératoire": "complication",
    "Consultation d'anesthésie": "consultation",
    "Pathologies de réanimation": "reanimation",
}

SEED_DATA: dict[str, list[str]] = {
    "Chirurgie Thoracique": [
        "Résection pulmonaire",
        "CPC",
        "Bronchoscopie (EBUS)",
        "Bronchoscopie rigide",
        "Transplantation pulmonaire"
    ],
    "Chirurgie Cardiaque": [
        "PAC sous CEC",
        "PAC à cœur battant",
        "Remplacement valvulaire aortique (RVAo)",
        "Remplacement valvulaire mitral (RVM/plastie)",
        "Aorte ascendante (TSC, Bentall, Tiron David)",
        "Transplantation cardiaque",
        "Assistances ventriculaires (LVAD/RVAD)"
    ],
    "Chirurgie Vasculaire": [
        "Aorte descendante (AAA)",
        "Endoprothèse aortique",
        "TAVI"
    ],
    "Gestes techniques": [
        "KTA (Cathéter artériel)",
        "KTC (Cathéter veineux central)",
        "Swan-Ganz (Cathéter artériel pulmonaire)",
        "Intubation double lumière",
        "Bloqueur bronchique",
        "Péridurale thoracique",
        "ALR para-sternale",
        "ALR périphérique (TAP block)",
        "ALR périphérique (Sciatique poplité)",
        "ALR périphérique (Fémoral)",
        "ETO peropératoire"
    ],
    "Consultation d'anesthésie": [
        "Consultation pré-opératoire",
        "Visite pré-anesthésique",
    ],
    "Pathologies de réanimation": [
        "Choc septique (réa)",
        "SDRA (réa)",
        "Choc cardiogénique (réa)",
        "Choc hémorragique (réa)",
        "Insuffisance rénale aiguë (réa)",
        "Intoxication médicamenteuse",
        "État de mal épileptique",
        "Polytraumatisme",
        "Hémorragie du post-partum",
        "Arrêt cardiaque (réa)",
        "Transplantation (réa)",
        "Mort encéphalique (réa)",
    ],
    "Complications post-opératoire": [
        "Choc hémorragique",
        "Choc cardiogénique",
        "Tamponnade",
        "ACR (Arrêt cardio-respiratoire)",
        "Choc septique",
        "SDRA",
        "Révision pour hémostase",
        "Insuffisance rénale aiguë (dialyse)",
        "AVC périopératoire"
    ]
}

# ---------------------------------------------------------------------------
# LC-CUSUM thresholds per gesture (literature-based)
# p0 = unacceptable failure rate (null hypothesis in Wald test)
# p1 = acceptable failure rate (alternative hypothesis)
# Convention: p0 = 2 × p1 (standard in the literature)
# Sources: Konrad et al. Anesth Analg 2003, Frontiers in Medicine (US-CEB),
#          NIH meta-analyses on PNB, DLT, CVC, arterial line success rates
# ---------------------------------------------------------------------------
LC_CUSUM_THRESHOLDS: dict[str, tuple[float, float]] = {
    # Simple / intermediate gestures: p0=0.20, p1=0.10
    "KTA (Cathéter artériel)": (0.20, 0.10),
    "KTC (Cathéter veineux central)": (0.20, 0.10),
    "Péridurale thoracique": (0.20, 0.10),           # Konrad: 10% acceptable
    "ALR para-sternale": (0.20, 0.10),
    "ALR périphérique (TAP block)": (0.20, 0.10),
    "ALR périphérique (Sciatique poplité)": (0.20, 0.10),
    "ALR périphérique (Fémoral)": (0.20, 0.10),
    # Complex gestures: p0=0.30, p1=0.15
    "Swan-Ganz (Cathéter artériel pulmonaire)": (0.30, 0.15),
    "Intubation double lumière": (0.30, 0.15),       # DLT malpositioning 33-50%
    "Bloqueur bronchique": (0.30, 0.15),
    "ETO peropératoire": (0.30, 0.15),               # Complex imaging
}

# Demo users — each resident at a specific DESAR semester for comprehensive testing
DEMO_USERS = [
    # ─── Residents at different DESAR phases ───
    {
        "email": "resident@aneslog.fr",
        "password": "resident123",
        "full_name": "Marie Dupont",
        "role": UserRole.resident,
        "semester": 2,           # Socle, early
        "cases_target": 5,
    },
    {
        "email": "celine.kuoch@aneslog.fr",
        "password": "resident123",
        "full_name": "Céline KUOCH",
        "role": UserRole.resident,
        "semester": 4,           # Approfondissement, early
        "cases_target": 5,
    },
    {
        "email": "maxime.aparicio@aneslog.fr",
        "password": "resident123",
        "full_name": "Maxime APARICIO",
        "role": UserRole.resident,
        "semester": 6,           # Approfondissement, mid
        "cases_target": 5,
    },
    {
        "email": "julien.pozzatti@aneslog.fr",
        "password": "resident123",
        "full_name": "Julien POZZATTI",
        "role": UserRole.resident,
        "semester": 8,           # Approfondissement, late
        "cases_target": 5,
    },
    {
        "email": "roberta@aneslog.fr",
        "password": "resident123",
        "full_name": "Roberta DA SILVA",
        "role": UserRole.resident,
        "semester": 9,           # Consolidation
        "cases_target": 5,
    },
    {
        "email": "andrei.mitre@aneslog.fr",
        "password": "resident123",
        "full_name": "Andrei MITRE",
        "role": UserRole.resident,
        "semester": 10,          # Consolidation, final year
        "cases_target": 5,
    },
    # ─── Senior ───
    {
        "email": "senior@aneslog.fr",
        "password": "senior123",
        "full_name": "Dr. Jean Martin",
        "role": UserRole.senior,
    },
]


def seed_competency_domains(db):
    """Seed the 7+1 DESAR competency domains and their competencies.
    
    On each run the competency list is reconciled with the reference
    COMPETENCIES dict: new items are added and stale items (names that
    no longer appear in the reference) are removed so the DB always
    matches the official maquette.
    """
    print("\n📚 Seeding DESAR competency domains...")
    
    domain_map = {}  # code → CompetencyDomain object
    
    for domain_data in COMPETENCY_DOMAINS:
        existing = db.query(CompetencyDomain).filter(
            CompetencyDomain.code == domain_data["code"]
        ).first()
        if not existing:
            domain = CompetencyDomain(**domain_data)
            db.add(domain)
            db.flush()
            domain_map[domain.code] = domain
            print(f"  ✓ Domaine {domain.code}: {domain.name}")
        else:
            domain_map[existing.code] = existing
            print(f"  ✓ Domaine existant: {existing.code}")
    
    # Seed competencies within each domain
    print("\n📋 Syncing competencies with official maquette...")
    competency_map = {}  # (domain_code, name) → Competency
    
    for domain_code, competencies in COMPETENCIES.items():
        domain = domain_map.get(domain_code)
        if not domain:
            continue

        # Build set of reference names for this domain
        reference_names = {c["name"] for c in competencies}

        # Remove stale competencies (names no longer in the maquette)
        existing_comps = db.query(Competency).filter(
            Competency.domain_id == domain.id,
        ).all()
        for ec in existing_comps:
            if ec.name not in reference_names:
                db.delete(ec)
                print(f"    − Supprimé: {domain_code}.{ec.name}")

        # Upsert current competencies
        for i, comp_data in enumerate(competencies, 1):
            existing = db.query(Competency).filter(
                Competency.domain_id == domain.id,
                Competency.name == comp_data["name"]
            ).first()
            if not existing:
                comp = Competency(
                    domain_id=domain.id,
                    name=comp_data["name"],
                    description=comp_data.get("description"),
                    display_order=i,
                )
                db.add(comp)
                db.flush()
                competency_map[(domain_code, comp.name)] = comp
                print(f"    + {domain_code}.{comp.name}")
            else:
                # Update display_order and description if changed
                existing.display_order = i
                existing.description = comp_data.get("description", existing.description)
                competency_map[(domain_code, existing.name)] = existing
    
    db.commit()
    return domain_map, competency_map


def link_procedures_to_competencies(db, domain_map):
    """Link existing procedures to competency domains via their first competency."""
    print("\n🔗 Linking procedures to competency domains...")
    
    for proc_name, domain_code in PROCEDURE_COMPETENCY_MAP.items():
        proc = db.query(Procedure).filter(Procedure.name == proc_name).first()
        domain = domain_map.get(domain_code)
        if proc and domain and not proc.competency_id:
            # Find the first competency in this domain to link to
            first_comp = db.query(Competency).filter(
                Competency.domain_id == domain.id
            ).order_by(Competency.display_order).first()
            if first_comp:
                proc.competency_id = first_comp.id
                print(f"    🔗 {proc.name} → {domain_code}")
    
    db.commit()


def seed_semesters(db, team):
    """Create realistic semester history for each resident at their specific DESAR stage."""
    print("\n📅 Seeding demo semesters...")
    
    # Diverse hospital rotation — realistic Île-de-France training
    # (hospital, service, chef_de_service)
    HOSPITAL_ROTATIONS = [
        ("Hôpital Marie Lannelongue", "Anesthésie-Réanimation Cardiovasculaire", "Pr. Olaf Mercier"),
        ("Hôpital Bicêtre", "Réanimation Chirurgicale", "Pr. Jacques Martin"),
        ("Hôpital Necker", "Anesthésie Pédiatrique", "Pr. Isabelle Constant"),
        ("Hôpital Cochin", "Anesthésie Obstétricale", "Pr. Anne Bhogal"),
        ("CHU Kremlin-Bicêtre", "Réanimation Médicale", "Pr. David Osman"),
        ("Hôpital Tenon", "Chirurgie Digestive", "Pr. Frédéric Aubrun"),
        ("Hôpital Lariboisière", "Neuro-Anesthésie", "Pr. Sébastien Pili-Floury"),
        ("Hôpital Saint-Louis", "Réanimation Polyvalente", "Pr. Benoît Plaud"),
        ("Hôpital Foch", "Chirurgie Thoracique", "Pr. Marc Fischler"),
        ("Hôpital Européen Georges Pompidou", "Chirurgie Vasculaire", "Pr. Bernard Cholley"),
    ]
    
    residents_data = {ud["email"]: ud for ud in DEMO_USERS if ud["role"] == UserRole.resident}
    
    residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.team_id == team.id,
    ).all()
    
    for user in residents:
        existing = db.query(Semester).filter(Semester.user_id == user.id).first()
        if existing:
            continue
        
        user_info = residents_data.get(user.email, {})
        current_sem = user_info.get("semester", 2)
        
        # Compute a realistic start date for S1 based on how many semesters completed
        from dateutil.relativedelta import relativedelta
        months_back = (current_sem - 1) * 6
        s1_start = date.today() - timedelta(days=months_back * 30)
        
        user.semester = current_sem
        
        shuffled_hospitals = list(HOSPITAL_ROTATIONS)
        random.shuffle(shuffled_hospitals)
        
        for s in range(1, 11):  # Always create all 10 blocks
            phase = Semester.phase_for_semester(s)
            
            if s <= current_sem:
                # Past & current semesters: fill in dates + hospital
                sem_start = s1_start + relativedelta(months=6 * (s - 1))
                sem_end = sem_start + relativedelta(months=6) - timedelta(days=1)
                hosp, serv, chef = shuffled_hospitals[(s - 1) % len(shuffled_hospitals)]
                subdiv = "Île-de-France"  # All demo users are in IDF
                if s == current_sem:
                    hosp = "Hôpital Marie Lannelongue"
                    serv = "Anesthésie-Réanimation Cardiovasculaire"
                    chef = "Pr. Olaf Mercier"
            else:
                # Future semesters: empty blocks
                sem_start = None
                sem_end = None
                subdiv = None
                hosp = None
                serv = None
                chef = None
            
            sem = Semester(
                user_id=user.id,
                number=s,
                phase=phase,
                start_date=sem_start,
                end_date=sem_end,
                subdivision=subdiv,
                hospital=hosp,
                service=serv,
                chef_de_service=chef,
                team_id=team.id,
                is_current=(s == current_sem),
            )
            db.add(sem)
        
        print(f"  ✓ {user.full_name}: S{current_sem} ({Semester.phase_for_semester(current_sem).value})")
    
    db.commit()


def seed_guard_logs(db):
    """Create realistic guard logs — more guards for advanced residents."""
    print("\n🛡️ Seeding demo guard logs...")
    
    guard_notes = [
        "Nuit calme, 2 entrées",
        "Garde chargée — 1 ACR, 3 admissions",
        "Appel réa pour intubation",
        "Transfert SMUR nuit, polytraumatisé",
        "Césarienne urgente 3h du matin",
        "Nuit tranquille, 1 extubation programmée",
        "2 admissions post-op compliquées",
        None, None, None,  # Some guards without notes
    ]
    
    residents = db.query(User).filter(User.role == UserRole.resident).all()
    
    for user in residents:
        existing = db.query(GuardLog).filter(GuardLog.user_id == user.id).first()
        if existing:
            continue
        
        # More guards for more advanced residents
        sem_number = user.semester or 2
        num_guards = sem_number * 3 + random.randint(0, 5)  # S2→6-11, S10→30-35
        
        # Get semesters with dates for this user to distribute guards
        semesters = db.query(Semester).filter(
            Semester.user_id == user.id,
            Semester.start_date.isnot(None),
        ).order_by(Semester.number).all()
        
        for i in range(num_guards):
            # Distribute guards across semesters
            if semesters:
                sem = random.choice(semesters)
                # Random date within semester bounds
                start = sem.start_date
                end = sem.end_date or date.today()
                days_range = max((end - start).days, 1)
                guard_date = start + timedelta(days=random.randint(0, days_range))
            else:
                guard_date = date.today() - timedelta(days=random.randint(0, 180))
                sem = None
            
            # Weight towards garde_24h (more common)
            guard_type = random.choices(
                [GuardType.garde_24h, GuardType.astreinte],
                weights=[0.7, 0.3],
            )[0]
            
            db.add(GuardLog(
                user_id=user.id,
                date=guard_date,
                guard_type=guard_type,
                semester_id=sem.id if sem else None,
                notes=random.choice(guard_notes),
            ))
        
        print(f"  ✓ {user.full_name}: {num_guards} gardes")
    
    db.commit()


# ── Autonomy weighting by semester (realistic progression) ────────────────
# S1-S2 (Socle): mostly "observed" and "assisted"
# S3-S5 (Approf early): balanced, moving toward "capable"
# S6-S8 (Approf late): mostly "capable" + "autonomous"
# S9-S10 (Consolidation): almost all "autonomous"
AUTONOMY_WEIGHTS = {
    1:  [0.60, 0.30, 0.08, 0.02],   # S1: 60% observed
    2:  [0.40, 0.35, 0.18, 0.07],   # S2: shifting to assisted
    3:  [0.15, 0.40, 0.30, 0.15],   # S3: mostly assisted
    4:  [0.08, 0.30, 0.40, 0.22],   # S4: moving to capable
    5:  [0.05, 0.15, 0.45, 0.35],   # S5: mostly capable
    6:  [0.03, 0.10, 0.37, 0.50],   # S6: half autonomous
    7:  [0.02, 0.08, 0.25, 0.65],   # S7: majority autonomous
    8:  [0.01, 0.04, 0.20, 0.75],   # S8: strong autonomous
    9:  [0.00, 0.02, 0.13, 0.85],   # S9: near-full autonomous
    10: [0.00, 0.01, 0.09, 0.90],   # S10: final year – autonomous
}

# Realistic case notes
CASE_NOTES = [
    "Patient ASA 2, pas de difficulté particulière",
    "Intubation difficile Cormack 3, VL utilisé",
    "Saignement peropératoire > 1L, transfusion",
    "Patient obèse, IOT au VL premier passage",
    "Rachianesthésie en S3, bon bloc sensitif",
    "Choc hémorragique corrigé par remplissage + NAD",
    "Ventilation unipulmonaire difficile, SpO2 88% corrigée",
    "CEC sans incident, sevrage inotrope facile",
    "Extubation sur table, patient stable",
    "Réinjection péridurale nécessaire à H4",
    "ETO : bonne cinétique VG post-chirurgie",
    "1ère césarienne sous rachianesthésie — bonne expérience",
    "Swan-Ganz posé pour monitoring hémodynamique",
    "Patient S1 — accompagné par le senior sur la pose de KTA",
    "Gestion du garrot pneumatique — patient drépanocytaire",
    "2ème ETO de la semaine — reconnaissance des coupes améliorée",
    "Cas pédiatrique : enfant 8 ans, IO sévoflurane",
    "TAVI : anesthésie locale + sédation, patient éveillé",
    "",  # some cases have no notes
    "",
    "",
]


def generate_fake_cases(db, user, cases_target):
    """Generate realistic fake cases with autonomy weighted by semester."""
    sem_number = user.semester or 2
    print(f"    -> Generating {cases_target} cases for {user.full_name} (S{sem_number}): ", end="", flush=True)
    
    # Pre-fetch procedures by category
    interventions = []
    gestures = []
    complications = []
    
    intervention_cats = ["Chirurgie Thoracique", "Chirurgie Cardiaque", "Chirurgie Vasculaire"]
    for cat_name in intervention_cats:
        c = db.query(Category).filter(Category.name == cat_name).first()
        if c:
            interventions.extend(db.query(Procedure).filter(Procedure.category_id == c.id).all())
            
    cat_gestes = db.query(Category).filter(Category.name == "Gestes techniques").first()
    if cat_gestes:
        gestures = db.query(Procedure).filter(Procedure.category_id == cat_gestes.id).all()
        
    cat_comps = db.query(Category).filter(Category.name == "Complications post-opératoire").first()
    if cat_comps:
        complications = db.query(Procedure).filter(Procedure.category_id == cat_comps.id).all()

    if not interventions:
        print("    ! No interventions found, skipping fake data.")
        return

    autonomy_levels = list(AutonomyLevel)
    weights = AUTONOMY_WEIGHTS.get(sem_number, AUTONOMY_WEIGHTS[5])
    
    # Get only semesters with dates (past/current) for distributing cases across time
    semesters = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.start_date.isnot(None),
    ).order_by(Semester.number).all()
    
    semester_map = {s.number: s for s in semesters}
    
    for case_i in range(cases_target):
        if (case_i + 1) % 5 == 0:
            print(f"{case_i+1}", end=" ", flush=True)
        case_uid = str(uuid.uuid4())
        
        # Distribute cases across semesters (more recent = more cases)
        # Weight toward later semesters
        if semesters:
            sem_weights = [(i + 1) ** 1.5 for i in range(len(semesters))]
            chosen_sem = random.choices(semesters, weights=sem_weights, k=1)[0]
            # Random date within this semester
            start = chosen_sem.start_date
            end = chosen_sem.end_date or date.today()
            days_range = max((end - start).days, 1)
            log_date = datetime.combine(
                start + timedelta(days=random.randint(0, days_range)),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            # Use the semester's autonomy weights (not the user's current)
            case_weights = AUTONOMY_WEIGHTS.get(chosen_sem.number, weights)
        else:
            days_ago = random.randint(0, 180)
            log_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
            chosen_sem = None
            case_weights = weights
        
        # Weighted surgery type — cardiovascular service sees mostly cardiac/thoracic
        surgery_type = random.choices(
            SURGERY_TYPES,
            weights=[15, 30, 20, 3, 3, 2, 3, 5, 3, 5, 3],  # heavy on cardio/thorac/vasc
            k=1,
        )[0]
        
        # 1. Main Intervention (Mandatory)
        intervention = random.choice(interventions)
        autonomy = random.choices(autonomy_levels, weights=case_weights, k=1)[0]
        notes = random.choice(CASE_NOTES)
        
        db.add(ProcedureLog(
            user_id=user.id,
            procedure_id=intervention.id,
            date=log_date,
            autonomy_level=autonomy,
            case_id=case_uid,
            notes=notes,
            surgery_type=surgery_type,
            semester_id=chosen_sem.id if chosen_sem else None,
        ))
        
        # 2. Gestures (0-3) — more gestures for advanced residents
        if gestures:
            max_gestures = min(3, 1 + sem_number // 3)  # S1-S3→1-2, S4-S6→2-3, S7+→3
            num_gestures = random.randint(0, max_gestures)
            if num_gestures > 0:
                selected_gestures = random.sample(gestures, min(num_gestures, len(gestures)))
                for g in selected_gestures:
                    g_autonomy = random.choices(autonomy_levels, weights=case_weights, k=1)[0]
                    db.add(ProcedureLog(
                        user_id=user.id,
                        procedure_id=g.id,
                        date=log_date,
                        autonomy_level=g_autonomy,
                        case_id=case_uid,
                        notes=notes,
                        surgery_type=surgery_type,
                        semester_id=chosen_sem.id if chosen_sem else None,
                    ))
                
        # 3. Complications (0-2) — slightly more common for advanced (they handle more)
        complication_chance = 0.15 + (sem_number * 0.02)  # S2→19%, S10→35%
        if complications and random.random() < complication_chance:
             num_comps = random.randint(1, 2)
             selected_comps = random.sample(complications, min(num_comps, len(complications)))
             complication_roles = list(ComplicationRole)
             # Weights for complications: Observé, Participé, Géré
             # More experienced → more likely to have managed
             comp_weights = case_weights[:3] if len(case_weights) >= 3 else [0.3, 0.4, 0.3]
             for c in selected_comps:
                 c_autonomy = random.choices(complication_roles, weights=comp_weights, k=1)[0]
                 db.add(ProcedureLog(
                    user_id=user.id,
                    procedure_id=c.id,
                    date=log_date,
                    autonomy_level=c_autonomy,
                    case_id=case_uid,
                    notes=notes,
                    surgery_type=surgery_type,
                    semester_id=chosen_sem.id if chosen_sem else None,
                 ))
    print(f"✓")  # Finish the progress line


def seed_procedure_competences(db, team):
    """Generate ProcedureCompetence records based on actual log data.
    
    For each resident and each procedure they've logged:
      - If autonomous_count >= MASTERY_THRESHOLD → mastered
      - Some mastered ones get senior_validated (locked)
    """
    from sqlalchemy import func
    
    THRESHOLD = ProcedureCompetence.MASTERY_THRESHOLD
    
    residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.team_id == team.id,
    ).all()
    
    senior = db.query(User).filter(
        User.role == UserRole.senior,
        User.team_id == team.id,
    ).first()
    
    if not residents or not senior:
        print("  ⚠ No residents or senior found, skipping competences.")
        return
    
    # Check if already seeded
    existing = db.query(ProcedureCompetence).count()
    if existing > 0:
        print(f"  ✓ {existing} competences already exist, skipping.")
        return
    
    print("\n🎯 Seeding procedure competences...")
    created = 0
    
    for resident in residents:
        # Count autonomous logs per procedure
        auto_counts = db.query(
            ProcedureLog.procedure_id,
            func.count(ProcedureLog.id).label("cnt"),
        ).filter(
            ProcedureLog.user_id == resident.id,
            ProcedureLog.autonomy_level == AutonomyLevel.autonomous,
        ).group_by(ProcedureLog.procedure_id).all()
        
        total_log_counts = db.query(
            ProcedureLog.procedure_id,
            func.count(ProcedureLog.id).label("cnt"),
        ).filter(
            ProcedureLog.user_id == resident.id,
        ).group_by(ProcedureLog.procedure_id).all()
        total_map = {pid: cnt for pid, cnt in total_log_counts}
        
        mastered_procs = [(pid, cnt) for pid, cnt in auto_counts if cnt >= THRESHOLD]
        
        for i, (proc_id, auto_cnt) in enumerate(mastered_procs):
            # ~60% get senior validated (locked)
            is_validated = random.random() < 0.6
            
            comp = ProcedureCompetence(
                user_id=resident.id,
                procedure_id=proc_id,
                is_mastered=True,
                mastered_at_log_count=total_map.get(proc_id, auto_cnt),
                mastered_date=datetime.now(timezone.utc) - timedelta(days=random.randint(1, 90)),
                senior_validated=is_validated,
                senior_validated_date=datetime.now(timezone.utc) - timedelta(days=random.randint(1, 30)) if is_validated else None,
                senior_validated_by=senior.id if is_validated else None,
            )
            db.add(comp)
            created += 1
    
    db.commit()
    print(f"  ✓ Created {created} competence records")


def seed():
    """Create tables and seed categories, procedures, and demo users."""
    # Create all tables
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. Seed DESAR competency domains and competencies
        domain_map, competency_map = seed_competency_domains(db)
        
        # 2. Seed categories and procedures
        print("\n📦 Seeding categories and procedures...")
        for category_name, procedure_names in SEED_DATA.items():
            cat = db.query(Category).filter(Category.name == category_name).first()
            section = CATEGORY_SECTIONS.get(category_name, "intervention")
            if not cat:
                cat = Category(name=category_name, section=section)
                db.add(cat)
                db.flush()
                print(f"  ✓ Catégorie: {category_name} (section={section})")
            elif cat.section != section:
                cat.section = section
                print(f"  ↻ Section corrigée: {category_name} → {section}")

            for proc_name in procedure_names:
                exists = (
                    db.query(Procedure)
                    .filter(Procedure.name == proc_name, Procedure.category_id == cat.id)
                    .first()
                )
                if not exists:
                    p0, p1 = LC_CUSUM_THRESHOLDS.get(proc_name, (None, None))
                    db.add(Procedure(
                        name=proc_name,
                        category_id=cat.id,
                        lc_cusum_p0=p0,
                        lc_cusum_p1=p1,
                    ))
                    threshold_info = f" (p0={p0}, p1={p1})" if p0 else ""
                    print(f"    + {proc_name}{threshold_info}")

        db.commit()
        
        # 3. Link procedures to competency domains
        link_procedures_to_competencies(db, domain_map)

        # 4. Seed Team
        team_name = "Anesth HML"
        team = db.query(Team).filter(Team.name == team_name).first()
        if not team:
            team = Team(name=team_name)
            db.add(team)
            db.commit()
            print(f"\n  ✓ Équipe: {team_name}")
        else:
            print(f"\n  ✓ Équipe existante: {team_name}")

        # 5. Seed demo users
        print("\n👤 Seeding demo users...")
        for user_data in DEMO_USERS:
            exists = db.query(User).filter(User.email == user_data["email"]).first()
            if not exists:
                new_user = User(
                    email=user_data["email"],
                    password_hash=hash_password(user_data["password"]),
                    full_name=user_data["full_name"],
                    role=user_data["role"],
                    is_active=True,
                    is_approved=True,
                    team_id=team.id,
                )
                db.add(new_user)
                db.flush()
                print(f"  ✓ {user_data['email']} ({user_data['role'].value})")

        db.commit()
        
        # 6. Seed semesters for residents
        seed_semesters(db, team)
        
        # 7. Generate fake cases (must be after semesters)
        print("\n📊 Generating fake cases...")
        for user_data in DEMO_USERS:
            if user_data["role"] == UserRole.resident:
                user = db.query(User).filter(User.email == user_data["email"]).first()
                if user:
                    # Only generate if no logs exist
                    log_count = db.query(ProcedureLog).filter(ProcedureLog.user_id == user.id).count()
                    if log_count == 0:
                        cases_target = user_data.get("cases_target", 50)
                        generate_fake_cases(db, user, cases_target)
        
        db.commit()
        
        # 8. Seed guard logs
        seed_guard_logs(db)
        
        # 9. Seed procedure competences
        seed_procedure_competences(db, team)
        
        print("\n✅ Seed completed successfully!")
    except Exception as e:
        db.rollback()
        print(f"\n❌ Seed error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("🌱 Seeding AnesLog database...\n")
    seed()
