import json
import os
from groq import Groq

def evaluate_match_with_llm(candidate_data: dict, job_offer_data: dict) -> dict:
    
    criteria = job_offer_data.get('criteria', [])
    if not criteria:
        return {"total_score": 0, "evaluations": [], "message": "Brak kryteriów u pracodawcy."}

    criteria_text = ""
    for c in criteria:
        criteria_text += f"- ID: {c.get('id')}, Opis: {c.get('description')}, Waga: {c.get('weight')}\n"

    candidate_desc = f"""
    Umiejętności/Doświadczenie/Szkolenia: {candidate_data.get('doswiadczenie', '')} {candidate_data.get('skills', '')}
    Języki: {candidate_data.get('languages', '')}
    Preferencje: {candidate_data.get('preferencje', '')}
    Lokalizacja: {candidate_data.get('miasto', '')}, {candidate_data.get('wojewodztwo', '')}
    Niepełnosprawność: {candidate_data.get('niepelnosprawnosc', 'Brak informacji')}
    """

    prompt = f"""
    Na podstawie podanych danych kandydata, oceń jak dobrze spełnia każdy punkt z kryteriów pracodawcy.
    Dla każdego kryterium wystaw obiektywną ocenę ('score') w postaci ułamka dziesiętnego od 0.0 do 1.0 (gdzie 1.0 to pełne spełnienie, a 0.0 to brak spełnienia).
    Dla każdej oceny dodaj jedno krótkie zdanie uzasadnienia ('justification').
    
    DANE KANDYDATA:
    {candidate_desc}
    
    KRYTERIA PRACODAWCY:
    {criteria_text}
    
    Zwróć wynik jako JSON zawierający listę w kluczu "evaluations". Np:
    {{
      "evaluations": [
        {{"id": 1, "score": 0.8, "justification": "Kandydat spełnia kryterium w dużej mierze."}}
      ]
    }}
    """

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        print("UWAGA: Brak klucza GROQ_API_KEY w zmiennych środowiskowych!")

    try:
        client = Groq(api_key=groq_api_key)
        
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Jesteś ekspertem HR pomagającym pracodawcy. Odpowiadaj wyłącznie w poprawnym i czystym formacie JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            model="llama-3.1-8b-instant", 
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        response_text = chat_completion.choices[0].message.content
        print("Odpowiedź Groq:", response_text)
        
        result_data = json.loads(response_text)
        evaluations_from_llm = result_data.get("evaluations", [])
        eval_map = {item["id"]: item for item in evaluations_from_llm}
        
        total_score = 0
        max_possible_score = 0
        final_evaluations = []
        
        for c in criteria:
            c_id = c.get('id')
            weight = c.get('weight', 1)
            max_possible_score += weight
            
            evaluated = eval_map.get(c_id, {"score": 0.0, "justification": "Model nie ocenił."})
            score = float(evaluated.get("score", 0.0))
            
            points_earned = score * weight
            total_score += points_earned
            
            final_evaluations.append({
                "id": c_id,
                "score": score,
                "earned_points": points_earned,
                "max_points": weight,
                "justification": evaluated.get("justification", "")
            })
            
        final_percentage = (total_score / max_possible_score) * 100 if max_possible_score > 0 else 0
        
        return {
            "final_match_percentage": round(final_percentage, 2),
            "total_score": round(total_score, 2),
            "max_possible_score": max_possible_score,
            "evaluations": final_evaluations
        }
            
    except Exception as e:
        print(f"Błąd przy odpytywaniu Groq API: {e}")
