"""
Database seeding script.
Run with:  python -m app.seed

===========================================================================
HOW TO ADD NEW PROCEDURES:
Just add entries to the SEED_DATA dictionary below.
The script will automatically create missing categories and procedures.
===========================================================================
"""
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from app.database import SessionLocal, engine, Base
from app.models import (
    User, Category, Procedure, ProcedureLog, AutonomyLevel,
    ComplicationRole, UserRole, Semester, Service,
    CompetencyDomain, Competency, ProcedureCompetence,
    GuardLog, GuardType, DesarPhase, CaseType,
)
from app.auth import hash_password

# ---------------------------------------------------------------------------
# DESAR Competency Domains (Journal Officiel, 28 avril 2017)
# ---------------------------------------------------------------------------
COMPETENCY_DOMAINS = [
    {"code": "A", "name": "Évaluation pré-opératoire",
     "description": "Examen pré-op, classification de risque, allergie, jeûne, prémédication",
     "phase_required": DesarPhase.socle, "display_order": 1},
    {"code": "B", "name": "Conduire une anesthésie générale",
     "description": "Induction, gestion de l'AG et des voies aériennes, agents intraveineux et halogénés",
     "phase_required": DesarPhase.socle, "display_order": 2},
    {"code": "C", "name": "Réveil de l'anesthésie",
     "description": "Surveillance, incidents-accidents, score d'Aldrete, NVPO",
     "phase_required": DesarPhase.socle, "display_order": 3},
    {"code": "D", "name": "Anesthésie loco-régionale",
     "description": "Rachianesthésie, péridurales, blocs périphériques écho-guidés",
     "phase_required": DesarPhase.socle, "display_order": 4},
    {"code": "E", "name": "Gestion de la douleur",
     "description": "Morphiniques, antalgiques non morphiniques, PCA, ALR pour l'analgésie post-opératoire",
     "phase_required": DesarPhase.socle, "display_order": 5},
    {"code": "F", "name": "Terrain et type de chirurgie",
     "description": "Adapter la stratégie au terrain (respiratoire, cardiovasculaire, neuro, obstétrique, pédiatrie…)",
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
    # Évaluer l'état du patient et préparer l'acte opératoire
    "A": [
        {"name": "Examen pré-opératoire", "description": "Consultation d'anesthésie, checklists, classification ASA"},
        {"name": "Gestion des voies aériennes (évaluation)", "description": "Évaluation prédictive de l'intubation difficile"},
        {"name": "Jeûne et prémédication", "description": "Règles de jeûne, anxiolyse, protocoles institutionnels"},
    ],
    # ── Domain B ─────────────────────────────────────────────────────
    # Conduire une anesthésie générale
    "B": [
        {"name": "Vérifications et procédures de contrôle", "description": "Check-list avant acte interventionnel sous anesthésie"},
        {"name": "Induction et gestion de l'AG", "description": "Hypnotiques, morphiniques, curares, entretien de l'anesthésie"},
        {"name": "Gestion des voies aériennes (pratique)", "description": "Intubation, masque laryngé, ventilation, intubation difficile"},
        {"name": "Monitorage peropératoire", "description": "Scope, PNI, SpO2, capnographie, monitorage invasif"},
        {"name": "Remplissage et transfusion", "description": "Solutés, produits sanguins, récupérateur péri-opératoire"},
    ],
    # ── Domain C ─────────────────────────────────────────────────────
    # Conduire le réveil de l'anesthésie
    "C": [
        {"name": "Physiopathologie du réveil", "description": "Surveillance, incidents-accidents, score d'Aldrete"},
        {"name": "Nausées et vomissements post-opératoires", "description": "Prévention et traitement des NVPO"},
    ],
    # ── Domain D ─────────────────────────────────────────────────────
    "D": [
        {"name": "Rachianesthésie", "description": "Indications, technique, complications"},
        {"name": "Anesthésie péridurale", "description": "Lombaire et thoracique, indications spécifiques"},
        {"name": "Blocs périphériques écho-guidés", "description": "Adducteurs, fémoraux, sciatiques, TAP, PECS"},
    ],
    # ── Domain E ─────────────────────────────────────────────────────
    # Gérer la douleur pendant et dans les suites d'une opération
    "E": [
        {"name": "Morphiniques et antagonistes", "description": "Utilisation et prescription, PCA"},
        {"name": "Antalgiques non morphiniques", "description": "Paracétamol, AINS, néfopam, kétamine"},
        {"name": "Techniques d'ALR pour l'analgésie", "description": "Cathéters périnerveux, péridurales analgésiques"},
    ],
    # ── Domain F ─────────────────────────────────────────────────────
    # Tenir compte des répercussions de l'anesthésie sur les grandes
    # fonctions ; adapter la stratégie au terrain et au type de chirurgie
    "F": [
        {"name": "F.a — Fonction respiratoire", "description": "Insuffisant respiratoire, asthme, chirurgie thoracique, thoracoscopie, œsophage"},
        {"name": "F.b — Fonction cardiovasculaire", "description": "Coronarien, valvulopathie, chirurgie cardiaque, CEC, pontages"},
        {"name": "F.c — Fonction neurologique", "description": "Neurochirurgie, rachis, HTIC, épilepsie"},
        {"name": "F.d — Obstétrique", "description": "Césarienne, analgésie du travail, éclampsie, hémorragie du post-partum"},
        {"name": "F.e — Pédiatrie", "description": "Nouveau-né, nourrisson, enfant, particularités pharmacologiques"},
        {"name": "F.f — Ambulatoire", "description": "Critères d'éligibilité, prise en charge, réhabilitation rapide"},
        {"name": "F.g — Urgence", "description": "Estomac plein, induction séquence rapide, polytraumatisé"},
        {"name": "F.h — Obésité et terrain particulier", "description": "SAOS, insuffisant hépatique ou rénal"},
        {"name": "F.i — ORL/Ophta/Stomatologie", "description": "Intubation nasale, jet ventilation, laser, saignement ORL"},
        {"name": "F.j — Hors bloc opératoire", "description": "Endoscopies digestives, radiologie interventionnelle, neuroradiologie"},
    ],
    # ── Domain G ─────────────────────────────────────────────────────
    # Utiliser les ultrasons en anesthésie-réanimation
    "G": [
        {"name": "Échographie cardiaque (ETT/ETO)", "description": "Coupes de base, évaluation cinétique, remplissage"},
        {"name": "Échographie pleuropulmonaire", "description": "Pneumothorax, épanchement, profil BLUE"},
    ],
    # ── CoBaTrICE (Réanimation) ──────────────────────────────────────
    # Compétences communes avec le MIR (Journal Officiel 28 avril 2017)
    "COBA": [
        {"name": "Approche structurée du patient grave", "description": "Identification, évaluation et traitement des défaillances viscérales"},
        {"name": "Réanimation cardiorespiratoire", "description": "Arrêt cardiaque : diagnostic, prise en charge, protocoles ALS"},
        {"name": "Ventilation artificielle", "description": "Indications, modes ventilatoires, sevrage, VNI"},
        {"name": "Sédation et analgésie en réanimation", "description": "Échelles de sédation, protocoles, curarisation"},
        {"name": "États de choc", "description": "Choc septique, hémorragique, cardiogénique, obstructif"},
        {"name": "IRA et EER", "description": "Diagnostic, indications de l'épuration, modalités"},
        {"name": "Défaillance hépatique aiguë", "description": "Encéphalopathie hépatique, transplantation hépatique"},
        {"name": "Troubles de l'hémostase", "description": "CIVD, thrombopénie, anti-agrégants, AVK, AOD"},
        {"name": "Infectiologie en réanimation", "description": "Pneumonies acquises sous ventilation, bactériémies, C. difficile"},
        {"name": "Neuro-réanimation", "description": "Traumatisme crânien, AVC, état de mal, mort encéphalique"},
        {"name": "Complications du péripartum", "description": "Mise en danger de la vie de la mère"},
        {"name": "Antibiothérapie en réanimation", "description": "Spécificités, pharmacocinétique"},
        {"name": "Produits sanguins labiles", "description": "Administration en toute sécurité"},
        {"name": "Remplissage et vasopresseurs", "description": "Solutés, médicaments vasomoteurs et inotropes"},
        {"name": "Évaluation hémodynamique invasive", "description": "Cathéters artériels, PiCCO, Swan-Ganz, échocardiographie"},
        {"name": "Nutrition en réanimation", "description": "Entérale et parentérale, protocoles, surveillance"},
        {"name": "Gestion des accès vasculaires", "description": "CVC, dialyse, PICC, complications"},
        {"name": "Brûlé", "description": "Réanimation initiale, surface, besoins en remplissage"},
        {"name": "Patient traumatisé", "description": "Soins pré et postopératoires"},
        {"name": "Conséquences physiques et psychologiques", "description": "Minimiser l'impact sur patients et familles"},
        {"name": "Soins de fin de vie et limitation thérapeutique", "description": "Éthique, entretien avec familles, collaboration multidisciplinaire"},
        {"name": "Communication et gestion d'équipe", "description": "Leadership, relève, annonce d'une mauvaise nouvelle"},
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
# ---------------------------------------------------------------------------
LC_CUSUM_THRESHOLDS: dict[str, tuple[float, float]] = {
    "KTA (Cathéter artériel)": (0.20, 0.10),
    "KTC (Cathéter veineux central)": (0.20, 0.10),
    "Péridurale thoracique": (0.20, 0.10),
    "ALR para-sternale": (0.20, 0.10),
    "ALR périphérique (TAP block)": (0.20, 0.10),
    "ALR périphérique (Sciatique poplité)": (0.20, 0.10),
    "ALR périphérique (Fémoral)": (0.20, 0.10),
    "Swan-Ganz (Cathéter artériel pulmonaire)": (0.30, 0.15),
    "Intubation double lumière": (0.30, 0.15),
    "Bloqueur bronchique": (0.30, 0.15),
    "ETO peropératoire": (0.30, 0.15),
}

# Minimal demo users — just 1 resident + 1 senior
DEMO_USERS = [
    {
        "email": "resident@aneslog.fr",
        "password": "resident123",
        "full_name": "Marie Dupont",
        "role": UserRole.resident,
        "semester": 4,
        "cases_target": 15,
    },
    {
        "email": "senior@aneslog.fr",
        "password": "senior123",
        "full_name": "Dr. Jean Martin",
        "role": UserRole.senior,
    },
]


def seed_competency_domains(db):
    """Seed the 7+1 DESAR competency domains and their competencies."""
    print("\n📚 Seeding DESAR competency domains...")
    
    domain_map = {}
    
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
    competency_map = {}
    
    for domain_code, competencies in COMPETENCIES.items():
        domain = domain_map.get(domain_code)
        if not domain:
            continue

        reference_names = {c["name"] for c in competencies}

        existing_comps = db.query(Competency).filter(
            Competency.domain_id == domain.id,
        ).all()
        for ec in existing_comps:
            if ec.name not in reference_names:
                db.delete(ec)
                print(f"    − Supprimé: {domain_code}.{ec.name}")

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
            first_comp = db.query(Competency).filter(
                Competency.domain_id == domain.id
            ).order_by(Competency.display_order).first()
            if first_comp:
                proc.competency_id = first_comp.id
                print(f"    🔗 {proc.name} → {domain_code}")
    
    db.commit()


def seed_semesters(db, service):
    """Create realistic semester history for the demo resident."""
    print("\n📅 Seeding demo semesters...")
    
    HOSPITAL_ROTATIONS = [
        ("Hôpital Marie Lannelongue", "Anesthésie-Réanimation Cardiovasculaire", "Pr. Olaf Mercier"),
        ("Hôpital Bicêtre", "Réanimation Chirurgicale", "Pr. Jacques Martin"),
        ("Hôpital Necker", "Anesthésie Pédiatrique", "Pr. Isabelle Constant"),
        ("Hôpital Cochin", "Anesthésie Obstétricale", "Pr. Anne Bhogal"),
    ]
    
    residents_data = {ud["email"]: ud for ud in DEMO_USERS if ud["role"] == UserRole.resident}
    
    residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.service_id == service.id,
    ).all()
    
    for user in residents:
        existing = db.query(Semester).filter(Semester.user_id == user.id).first()
        if existing:
            continue
        
        user_info = residents_data.get(user.email, {})
        current_sem = user_info.get("semester", 2)
        
        from dateutil.relativedelta import relativedelta
        months_back = (current_sem - 1) * 6
        s1_start = date.today() - timedelta(days=months_back * 30)
        
        user.semester = current_sem
        
        shuffled_hospitals = list(HOSPITAL_ROTATIONS)
        random.shuffle(shuffled_hospitals)
        
        for s in range(1, 11):
            phase = Semester.phase_for_semester(s)
            
            if s <= current_sem:
                sem_start = s1_start + relativedelta(months=6 * (s - 1))
                sem_end = sem_start + relativedelta(months=6) - timedelta(days=1)
                hosp, serv, chef = shuffled_hospitals[(s - 1) % len(shuffled_hospitals)]
                subdiv = "Île-de-France"
                if s == current_sem:
                    hosp = "Hôpital Marie Lannelongue"
                    serv = "Anesthésie-Réanimation Cardiovasculaire"
                    chef = "Pr. Olaf Mercier"
            else:
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
                service_name=serv,
                chef_de_service=chef,
                service_id=service.id if s == current_sem else None,
                is_current=(s == current_sem),
            )
            db.add(sem)
        
        print(f"  ✓ {user.full_name}: S{current_sem} ({Semester.phase_for_semester(current_sem).value})")
    
    db.commit()


def seed_guard_logs(db):
    """Create realistic guard logs."""
    print("\n🛡️ Seeding demo guard logs...")
    
    guard_notes = [
        "Nuit calme, 2 entrées",
        "Garde chargée — 1 ACR, 3 admissions",
        "Appel réa pour intubation",
        None, None,
    ]
    
    residents = db.query(User).filter(User.role == UserRole.resident).all()
    
    for user in residents:
        existing = db.query(GuardLog).filter(GuardLog.user_id == user.id).first()
        if existing:
            continue
        
        sem_number = user.semester or 2
        num_guards = sem_number * 3 + random.randint(0, 5)
        
        semesters = db.query(Semester).filter(
            Semester.user_id == user.id,
            Semester.start_date.isnot(None),
        ).order_by(Semester.number).all()
        
        for i in range(num_guards):
            if semesters:
                sem = random.choice(semesters)
                start = sem.start_date
                end = sem.end_date or date.today()
                days_range = max((end - start).days, 1)
                guard_date = start + timedelta(days=random.randint(0, days_range))
            else:
                guard_date = date.today() - timedelta(days=random.randint(0, 180))
                sem = None
            
            guard_type = random.choices(
                [GuardType.garde, GuardType.astreinte],
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


# ── Autonomy weighting by semester ────────────────────────────────────
AUTONOMY_WEIGHTS = {
    1:  [0.60, 0.30, 0.08, 0.02],
    2:  [0.40, 0.35, 0.18, 0.07],
    3:  [0.15, 0.40, 0.30, 0.15],
    4:  [0.08, 0.30, 0.40, 0.22],
    5:  [0.05, 0.15, 0.45, 0.35],
    6:  [0.03, 0.10, 0.37, 0.50],
    7:  [0.02, 0.08, 0.25, 0.65],
    8:  [0.01, 0.04, 0.20, 0.75],
    9:  [0.00, 0.02, 0.13, 0.85],
    10: [0.00, 0.01, 0.09, 0.90],
}

CASE_NOTES = [
    "Patient ASA 2, pas de difficulté particulière",
    "Intubation difficile Cormack 3, VL utilisé",
    "Saignement peropératoire > 1L, transfusion",
    "CEC sans incident, sevrage inotrope facile",
    "Ventilation unipulmonaire difficile, SpO2 88% corrigée",
    "",
    "",
    "",
]


def generate_fake_cases(db, user, cases_target):
    """Generate realistic fake cases with autonomy weighted by semester."""
    sem_number = user.semester or 2
    print(f"    -> Generating {cases_target} cases for {user.full_name} (S{sem_number}): ", end="", flush=True)
    
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
    
    semesters = db.query(Semester).filter(
        Semester.user_id == user.id,
        Semester.start_date.isnot(None),
    ).order_by(Semester.number).all()
    
    for case_i in range(cases_target):
        if (case_i + 1) % 5 == 0:
            print(f"{case_i+1}", end=" ", flush=True)
        case_uid = str(uuid.uuid4())
        
        if semesters:
            sem_weights = [(i + 1) ** 1.5 for i in range(len(semesters))]
            chosen_sem = random.choices(semesters, weights=sem_weights, k=1)[0]
            start = chosen_sem.start_date
            end = chosen_sem.end_date or date.today()
            days_range = max((end - start).days, 1)
            log_date = datetime.combine(
                start + timedelta(days=random.randint(0, days_range)),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            case_weights = AUTONOMY_WEIGHTS.get(chosen_sem.number, weights)
        else:
            days_ago = random.randint(0, 180)
            log_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
            chosen_sem = None
            case_weights = weights
        
        surgery_type = random.choices(
            SURGERY_TYPES,
            weights=[15, 30, 20, 3, 3, 2, 3, 5, 3, 5, 3],
            k=1,
        )[0]
        
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
        
        if gestures:
            max_gestures = min(3, 1 + sem_number // 3)
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
                
        complication_chance = 0.15 + (sem_number * 0.02)
        if complications and random.random() < complication_chance:
             num_comps = random.randint(1, 2)
             selected_comps = random.sample(complications, min(num_comps, len(complications)))
             complication_roles = list(ComplicationRole)
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
    print(f"✓")


def seed_procedure_competences(db, service):
    """Generate ProcedureCompetence records based on actual log data."""
    from sqlalchemy import func
    
    THRESHOLD = ProcedureCompetence.MASTERY_THRESHOLD
    
    residents = db.query(User).filter(
        User.role == UserRole.resident,
        User.service_id == service.id,
    ).all()
    
    senior = db.query(User).filter(
        User.role == UserRole.senior,
        User.service_id == service.id,
    ).first()
    
    if not residents or not senior:
        print("  ⚠ No residents or senior found, skipping competences.")
        return
    
    existing = db.query(ProcedureCompetence).count()
    if existing > 0:
        print(f"  ✓ {existing} competences already exist, skipping.")
        return
    
    print("\n🎯 Seeding procedure competences...")
    created = 0
    
    for resident in residents:
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

        # 4. Seed Service (replaces Team)
        service = db.query(Service).filter(Service.name == "Anesthésie").first()
        if not service:
            service = Service(
                name="Anesthésie",
                hospital="Hôpital Marie Lannelongue",
                city="Le Plessis-Robinson",
                region="Île-de-France",
                slug="marie-lannelongue-anesthesie",
            )
            db.add(service)
            db.commit()
            print(f"\n  ✓ Service: {service.display_name}")
        else:
            print(f"\n  ✓ Service existant: {service.display_name}")

        # 5. Seed demo users
        print("\n👤 Seeding demo users...")
        for user_data in DEMO_USERS:
            exists = db.query(User).filter(User.email == user_data["email"]).first()
            if not exists:
                is_admin = user_data["role"] == UserRole.senior
                new_user = User(
                    email=user_data["email"],
                    password_hash=hash_password(user_data["password"]),
                    full_name=user_data["full_name"],
                    role=user_data["role"],
                    is_active=True,
                    is_approved=True,
                    service_id=service.id,
                    is_service_admin=is_admin,
                )
                db.add(new_user)
                db.flush()
                
                # Update service created_by
                if is_admin and not service.created_by:
                    service.created_by = new_user.id
                    
                print(f"  ✓ {user_data['email']} ({user_data['role'].value}){' [admin]' if is_admin else ''}")

        db.commit()
        
        # 6. Seed semesters for residents
        seed_semesters(db, service)
        
        # 7. Generate fake cases
        print("\n📊 Generating fake cases...")
        for user_data in DEMO_USERS:
            if user_data["role"] == UserRole.resident:
                user = db.query(User).filter(User.email == user_data["email"]).first()
                if user:
                    log_count = db.query(ProcedureLog).filter(ProcedureLog.user_id == user.id).count()
                    if log_count == 0:
                        cases_target = user_data.get("cases_target", 15)
                        generate_fake_cases(db, user, cases_target)
        
        db.commit()
        
        # 8. Seed guard logs
        seed_guard_logs(db)
        
        # 9. Seed procedure competences
        seed_procedure_competences(db, service)
        
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
