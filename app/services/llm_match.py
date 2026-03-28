import json
import os
from groq import Groq

def _build_candidate_string(c: dict) -> str:
    return f"""
    - Doświadczenie: {c.get('doswiadczenie', 'Brak')}
    - Umiejętności (Twarde/Miękkie): {c.get('skills', 'Brak')}
    - Języki: {c.get('languages', 'Brak')}
    - Preferencje zawodowe: {c.get('preferencje', 'Brak')}
    - Lokalizacja (Gotowość): {c.get('miasto', '')}, {c.get('wojewodztwo', '')}
    - Certyfikaty/Szkolenia: {c.get('szkolenia', 'Brak')}
    - Status na rynku (ZUS/Mobywatel/Niepełnosprawność): {c.get('status_rynkowy', 'Brak')}, {c.get('niepelnosprawnosc', 'Brak niepełnosprawności')}
    """

def _build_job_string(j: dict) -> str:
    return f"""
    - Stanowisko: {j.get('stanowisko', '')} ({j.get('poziom_stanowiska', '')})
    - Tryb pracy i wymiar: {j.get('tryb_pracy', '')}, {j.get('wymiar_etatu', '')}
    - Rodzaj umowy: {j.get('rodzaj_umowy', '')}
    - Min. Doświadczenie i Wykształcenie: {j.get('min_doswiadczenie', '')}, {j.get('min_wyksztalcenie', '')}
    - Wynagrodzenie: {j.get('wynagrodzenie', '')}
    - Lokalizacja pracy: {j.get('lokalizacja', '')}
    """

def evaluate_match_with_llm(candidate_data: dict, job_offer_data: dict) -> dict:
    criteria_list = job_offer_data.get('criteria', [])
    if not criteria_list:
        criteria_list = [
            {"id": 1, "description": "Dopasowanie doświadczenia kandydata do wymaganego poziomu.", "weight": 5},
            {"id": 2, "description": "Lokalizacja kandydata a tryb pracy i lokalizacja firmy.", "weight": 3},
            {"id": 3, "description": "Dopasowanie umiejętności/języków do specyfiki stanowiska.", "weight": 4}
        ]

    criteria_text = "\n".join([f"- ID: {c.get('id')}, Wymaganie: {c.get('description')}, Waga/Istotność: {c.get('weight')}" for c in criteria_list])
    
    candidate_desc = _build_candidate_string(candidate_data)
    job_desc = _build_job_string(job_offer_data)

    prompt = f"""
    Zadanie: Smart Match Kandydat -> Oferta Pracy.
    Bądź bardzo rygorystyczny i obiektywny. Nie domyślaj się umiejętności, jeżeli nie wynikają jednoznacznie ze zgłoszenia.
    Oceń jak precyzyjnie kandydat odpowiada na Ofertę na podstawie konkretnych Kryteriów.
    
    [PROFIL KANDYDATA]:
    {candidate_desc}
    
    [PROFIL OFERTY (KONTEKST)]:
    {job_desc}
    
    [KRYTERIA DO OCENY (od 0.0 do 1.0)]:
    {criteria_text}
    
    WYMÓG ZWROTNY: Output wyłącznie jako obiekt JSON z kluczem 'evaluations', przypisujący ocenę i bardzo krótkie ('justification') dla KAŻDEGO ID z listy kryteriów. Przykład:
    {{"evaluations": [{{"id": 1, "score": 0.8, "justification": "Ma 3 lata stażu w dziale X."}}]}}
    """

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
         return {"final_match_percentage": 50, "evaluations": [], "message": "Brak klucza API"}

    try:
        client = Groq(api_key=groq_api_key)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Jesteś analitykiem rekrutacji. Zwracasz wyłącznie czysty JSON."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        response_text = chat_completion.choices[0].message.content
        result_data = json.loads(response_text)
        
        evaluations_from_llm = result_data.get("evaluations", [])
        eval_map = {item["id"]: item for item in evaluations_from_llm}
        
        total_score = 0
        max_possible_score = 0
        final_evaluations = []
        
        for c in criteria_list:
            c_id = c.get('id')
            weight = c.get('weight', 1)
            max_possible_score += weight
            
            evaluated = eval_map.get(c_id, {"score": 0.0, "justification": "Brak precyzyjnej oceny przez model."})
            raw_score = evaluated.get("score")
            score = float(raw_score) if raw_score is not None else 0.0
            
            points_earned = score * weight
            total_score += points_earned
            
            final_evaluations.append({
                "description": c.get("description"),
                "score": score,
                "earned_points": points_earned,
                "max_points": weight,
                "justification": evaluated.get("justification", "")
            })
            
        final_percentage = (total_score / max_possible_score) * 100 if max_possible_score > 0 else 0
        
        return {
            "final_match_percentage": round(final_percentage, 2),
            "evaluations": final_evaluations
        }
            
    except Exception as e:
        print(f"LLM Error: {e}")
        return {"final_match_percentage": 0, "evaluations": []}
