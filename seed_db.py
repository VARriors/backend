from app import db
from bson.objectid import ObjectId
from app.services.candidate_questionnaire_service import build_default_questionnaire, now_iso

def init_db():
    candidate_id = "65f1a2b3c4d5e6f7a8b9c0d1"
    object_id = ObjectId(candidate_id)
    
    # Usuwamy jeśli istnieje
    db['candidates'].delete_one({"_id": object_id})
    
    questionnaire = build_default_questionnaire()
    # Wypełniamy kilka pól domyślnie
    questionnaire["fields"]["imie"]["value"] = "Jan"
    questionnaire["fields"]["nazwisko"]["value"] = "Kowalski"
    questionnaire["fields"]["preferencje"]["value"] = ["Gastronomia"]
    questionnaire["fields"]["pref_typ_umowy"]["value"] = "Umowa o pracę"
    questionnaire["fields"]["pref_wymiar_etatu"]["value"] = "Pełny etat"
    questionnaire["fields"]["obszar_poszukiwan"]["value"] = "Mazowieckie, Warszawa"
    
    candidate = {
        "_id": object_id,
        "first_name": "Jan",
        "last_name": "Kowalski",
        "email": "jan.kowalski@example.com",
        "questionnaire": questionnaire,
        "created_at": now_iso()
    }
    
    db['candidates'].insert_one(candidate)
    print(f"Kandydat {candidate_id} został dodany do bazy.")

    # Dodajemy przykładowe oferty pracy z pełnymi danymi
    db['jobs'].delete_many({})
    
    jobs = [
        {
            "title": "Kucharz",
            "company": "Restauracja Smak",
            "location": "Warszawa, Mazowieckie",
            "category": "Gastronomia",
            "description": "Przygotowywanie wysokiej jakości dań kuchni polskiej i europejskiej, dbanie o standardy serwowania oraz współpraca z zespołem pomocniczym.",
            "salary_range": "6000 - 8000 PLN brutto",
            "employment_type": "Umowa o pracę",
            "work_time": "Pełny etat",
            "work_mode": "Stacjonarna",
            "position_level": "Mid",
            "min_experience": "2 lata",
            "min_education": "Zawodowe",
            "languages": ["polski", "angielski"],
            "expectations": "Pasja do gotowania, znajomość norm HACCP oraz wysoka kultura osobista i punktualność.",
            "responsibilities": ["Przygotowywanie dań zgodnie z recepturą", "Dbanie o stan techniczny urządzeń kuchennych", "Nadzór nad gospodarką magazynową"],
            "benefits": ["Prywatna opieka medyczna", "Posiłki pracownicze", "Premie uznaniowe"],
            "tags": ["kuchnia polska", "HACCP"],
            "application_deadline": "2024-05-30",
            "requires_cv": False,
            "created_at": now_iso()
        },
        {
            "title": "Sprzedawca - Kasjer",
            "company": "Market Polka",
            "location": "Kraków, Małopolskie",
            "category": "Sprzedaż",
            "description": "Bezpośrednia obsługa klientów, dbanie o estetykę ekspozycji towarów oraz zapewnienie pozytywnego wizerunku sklepu.",
            "salary_range": "4500 - 5500 PLN brutto",
            "employment_type": "Umowa zlecenie",
            "work_time": "½ etatu",
            "work_mode": "Stacjonarna",
            "position_level": "Junior",
            "min_experience": "Brak",
            "min_education": "Średnie",
            "languages": ["polski"],
            "expectations": "Komunikatywność, zaangażowanie w powierzone zadania oraz gotowość do pracy zmianowej.",
            "responsibilities": ["Obsługa kasy fiskalnej", "Rozkładanie towaru", "Pomoc klientom"],
            "benefits": ["Elastyczny grafik", "Zniżki pracownicze"],
            "tags": ["handel", "obsługa klienta"],
            "application_deadline": "2024-04-15",
            "requires_cv": True,
            "cv_required_reason": "Wymagane doświadczenie w obsłudze klienta",
            "created_at": now_iso()
        }
    ]
    
    db['jobs'].insert_many(jobs)
    print(f"Dodano {len(jobs)} przykładowych ofert pracy.")

    # Dodajemy przykładowe aplikacje
    db['applications'].delete_many({})
    
    # Pobieramy kucharza i sprzedawcę
    cook_job = db['jobs'].find_one({"title": "Kucharz"})
    cashier_job = db['jobs'].find_one({"title": "Sprzedawca - Kasjer"})
    
    if cook_job and cashier_job:
        applications = [
            {
                "candidate_id": str(candidate_id),
                "employer_id": "mock-employer-1",
                "job_id": str(cook_job['_id']),
                "status": "UNREAD",
                "created_at": now_iso(),
                "updated_at": now_iso()
            }
        ]
        
        # Dodajemy kucharzowi przypisanie do mock-employer-1
        db['jobs'].update_one({"_id": cook_job['_id']}, {"$set": {"employer_id": "mock-employer-1"}})
        db['jobs'].update_one({"_id": cashier_job['_id']}, {"$set": {"employer_id": "mock-employer-1"}})
        
        db['applications'].insert_many(applications)
        print(f"Dodano {len(applications)} przykładowych aplikacji.")

if __name__ == "__main__":
    init_db()
