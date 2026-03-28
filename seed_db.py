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

if __name__ == "__main__":
    init_db()
