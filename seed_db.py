from app import db
from bson.objectid import ObjectId
from app.services.candidate_questionnaire_service import build_default_questionnaire, now_iso

def init_db():
    candidate_id = "65f1a2b3c4d5e6f7a8b9c0d1"
    candidate_email = "jan.kowalski@example.com"
    object_id = ObjectId(candidate_id)

    # Czyścimy wszystkie duplikaty demo-kandydata (po _id i e-mailu).
    db['candidates'].delete_many({
        "$or": [
            {"_id": object_id},
            {"email": candidate_email},
        ]
    })

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
        "email": candidate_email,
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
            "salary_range": "6000 - 8000",
            "employment_type": "Umowa o pracę",
            "work_time": "Pełny etat",
            "work_mode": "Stacjonarna",
            "position_level": "Mid",
            "min_experience": "2 lata",
            "min_education": "Zawodowe",
            "languages": ["polski", "angielski"],
            "expectations": "Pasja do gotowania, znajomość norm HACCP oraz wysoka kultura osobista i punktualność.",
            "responsibilities": ["Przygotowywanie dań zgodnie z recepturą",
                                 "Dbanie o stan techniczny urządzeń kuchennych", "Nadzór nad gospodarką magazynową"],
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
            "salary_range": "4500 - 5500",
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
        },
        {
            "title": "Pracownik magazynu",
            "company": "LogiPack",
            "location": "Łódź, Łódzkie",
            "category": "Praca fizyczna",
            "description": "Kompletowanie zamówień, przyjmowanie dostaw oraz przygotowanie paczek do wysyłki.",
            "salary_range": "4800 - 6200",
            "employment_type": "Umowa o pracę",
            "work_time": "Pełny etat",
            "work_mode": "Stacjonarna",
            "position_level": "Junior",
            "min_experience": "Brak",
            "min_education": "Podstawowe",
            "languages": ["polski"],
            "expectations": "Sprawność fizyczna, dokładność i gotowość do pracy zmianowej.",
            "responsibilities": ["Kompletowanie towaru", "Załadunek i rozładunek", "Dbanie o porządek w magazynie"],
            "benefits": ["Premia frekwencyjna", "Dofinansowanie dojazdów"],
            "tags": ["magazyn", "praca zmianowa"],
            "application_deadline": "2024-06-15",
            "requires_cv": False,
            "created_at": now_iso()
        }
    ]

    db['jobs'].insert_many(jobs)
    print(f"Dodano {len(jobs)} przykładowych ofert pracy.")

    # Na starcie nie seedujemy żadnych aplikacji (oferty mają być "czyste").
    db['applications'].delete_many({})

    # Pobieramy kucharza i sprzedawcę
    cook_job = db['jobs'].find_one({"title": "Kucharz"})
    cashier_job = db['jobs'].find_one({"title": "Sprzedawca - Kasjer"})
    warehouse_job = db['jobs'].find_one({"title": "Pracownik magazynu"})

    if cook_job and cashier_job and warehouse_job:
        # Dodajemy kucharzowi przypisanie do mock-employer-1
        db['jobs'].update_one({"_id": cook_job['_id']}, {"$set": {"employer_id": "mock-employer-1"}})
        db['jobs'].update_one({"_id": cashier_job['_id']}, {"$set": {"employer_id": "mock-employer-1"}})
        db['jobs'].update_one({"_id": warehouse_job['_id']}, {"$set": {"employer_id": "mock-employer-1"}})

    print("Seed zakończony bez aplikacji startowych.")


if __name__ == "__main__":
    init_db()
