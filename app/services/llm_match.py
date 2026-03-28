import json
import os
import re
from typing import Any, Dict, List

from groq import Groq


DEFAULT_CRITERIA = [
    {"id": 1, "description": "Skills and experience fit", "weight": 5},
    {"id": 2, "description": "Location and work mode fit", "weight": 3},
    {"id": 3, "description": "Preferences and role fit", "weight": 4},
]


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for item in value.values():
            text = _to_text(item)
            if text:
                parts.append(text)
        return " ".join(parts)
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _to_text(item)
            if text:
                parts.append(text)
        return " ".join(parts)
    return _safe_string(value)


def _tokenize(value: Any) -> set:
    text = _to_text(value).lower()
    tokens = re.findall(r"[\w+#]{2,}", text, flags=re.UNICODE)
    return set(tokens)


def _collect_candidate_tokens(candidate_data: Dict[str, Any]) -> set:
    fields = [
        candidate_data.get("skills"),
        candidate_data.get("languages"),
        candidate_data.get("preferencje"),
        candidate_data.get("doswiadczenie"),
        candidate_data.get("questionnaire"),
        candidate_data.get("extracted_data"),
    ]
    tokens = set()
    for field in fields:
        tokens.update(_tokenize(field))
    return tokens


def _collect_job_tokens(job_data: Dict[str, Any]) -> set:
    fields = [
        job_data.get("title"),
        job_data.get("description"),
        job_data.get("category"),
        job_data.get("required_skills"),
        job_data.get("requiredSkills"),
        job_data.get("criteria"),
        job_data.get("stanowisko"),
    ]
    tokens = set()
    for field in fields:
        tokens.update(_tokenize(field))
    return tokens


def _extract_candidate_location(candidate_data: Dict[str, Any]) -> str:
    parts = [
        candidate_data.get("miasto"),
        candidate_data.get("wojewodztwo"),
        candidate_data.get("location"),
        candidate_data.get("obszar_poszukiwan"),
    ]
    return " ".join([_safe_string(part) for part in parts if _safe_string(part)]).strip().lower()


def _extract_job_location(job_data: Dict[str, Any]) -> str:
    parts = [
        job_data.get("location"),
        job_data.get("lokalizacja"),
        job_data.get("tryb_pracy"),
    ]
    return " ".join([_safe_string(part) for part in parts if _safe_string(part)]).strip().lower()


def _extract_candidate_preferences(candidate_data: Dict[str, Any]) -> str:
    parts = [
        candidate_data.get("preferencje"),
        candidate_data.get("questionnaire"),
    ]
    return _to_text(parts).lower()


def _extract_job_role_text(job_data: Dict[str, Any]) -> str:
    parts = [
        job_data.get("title"),
        job_data.get("category"),
        job_data.get("stanowisko"),
    ]
    return _to_text(parts).lower()


def _evaluate_match_heuristic(candidate_data: Dict[str, Any], job_offer_data: Dict[str, Any]) -> Dict[str, Any]:
    criteria_list = job_offer_data.get("criteria", [])
    if not criteria_list:
        criteria_list = DEFAULT_CRITERIA

    candidate_tokens = _collect_candidate_tokens(candidate_data)
    job_tokens = _collect_job_tokens(job_offer_data)
    required_skills = job_offer_data.get("required_skills") or job_offer_data.get("requiredSkills") or []

    if isinstance(required_skills, list) and required_skills:
        required_tokens = set()
        for skill in required_skills:
            required_tokens.update(_tokenize(skill))
        overlap_base = required_tokens if required_tokens else job_tokens
    else:
        overlap_base = job_tokens

    if overlap_base:
        overlap_ratio = len(candidate_tokens.intersection(overlap_base)) / len(overlap_base)
    else:
        overlap_ratio = 0.5
    skills_score = max(0.0, min(1.0, overlap_ratio * 1.4))

    candidate_location = _extract_candidate_location(candidate_data)
    job_location = _extract_job_location(job_offer_data)
    if any(tag in job_location for tag in ["remote", "zdal", "hybrid", "hybryd"]):
        location_score = 1.0
    elif not candidate_location or not job_location:
        location_score = 0.5
    elif candidate_location in job_location or job_location in candidate_location:
        location_score = 1.0
    elif candidate_location.split(" ")[0] in job_location:
        location_score = 0.7
    else:
        location_score = 0.25

    preference_tokens = _tokenize(_extract_candidate_preferences(candidate_data))
    role_tokens = _tokenize(_extract_job_role_text(job_offer_data))
    if preference_tokens and role_tokens:
        preference_overlap = len(preference_tokens.intersection(role_tokens)) / len(role_tokens)
    else:
        preference_overlap = 0.5
    preference_score = max(0.0, min(1.0, preference_overlap * 1.8))

    per_criterion_score: List[float] = [skills_score, location_score, preference_score]
    total_score = 0.0
    max_possible_score = 0.0
    final_evaluations = []

    for index, criterion in enumerate(criteria_list):
        weight = float(criterion.get("weight", 1) or 1)
        score = per_criterion_score[index] if index < len(per_criterion_score) else skills_score
        points_earned = score * weight
        total_score += points_earned
        max_possible_score += weight

        final_evaluations.append({
            "description": criterion.get("description", f"Criterion {index + 1}"),
            "score": round(score, 4),
            "earned_points": round(points_earned, 4),
            "max_points": weight,
            "justification": "Heuristic score for demo mode.",
        })

    final_percentage = (total_score / max_possible_score) * 100 if max_possible_score > 0 else 0
    return {
        "final_match_percentage": round(final_percentage, 2),
        "evaluations": final_evaluations,
        "summary": "Ocena heurystyczna dla trybu demonstracyjnego. Dokładna analiza wymaga aktywnego modelu AI.",
        "source": "heuristic",
    }

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
        criteria_list = DEFAULT_CRITERIA

    criteria_text = "\n".join([f"- ID: {c.get('id')}, Wymaganie: {c.get('description')}, Waga/Istotność: {c.get('weight')}" for c in criteria_list])
    
    candidate_desc = _build_candidate_string(candidate_data)
    job_desc = _build_job_string(job_offer_data)

    prompt = f"""
    Zadanie: Smart Match Kandydat -> Oferta Pracy.
    Wciel się w wyjątkowo wyrozumiałego i optymistycznego rekrutera. Twoim celem jest ZNALEZIENIE POTENCJAŁU kandydata.
    Nie oceniaj zbyt restrykcyjnie. Nawet jeśli kandydat nie ma "wow" kwalifikacji, ale ma szanse się sprawdzić, daj mu wyższą ocenę.
    Używaj skali 0.0 do 1.0 (możesz dać np. 0.6 jeśli kandydat jest po prostu "okej", daje radę, ale ma luki).
    - 0.8 do 1.0: Świetne dopasowanie.
    - 0.5 do 0.7: Przeciętny kandydat, brakuje mu trochę do ideału, ale "jest okej" i posiada chęci.
    - 0.3 do 0.4: Słabsze dopasowanie, ale wciąż ma jakiś luźny związek ze stanowiskiem.
    - 0.0: Stosuj TYLKO wtedy, gdy stanowisko i kandydat to dwa kompletnie inne, wykluczające się światy.
    
    [PROFIL KANDYDATA]:
    {candidate_desc}
    
    [PROFIL OFERTY (KONTEKST)]:
    {job_desc}
    
    [KRYTERIA DO OCENY (od 0.0 do 1.0)]:
    {criteria_text}
    
    WYMÓG ZWROTNY: Output wyłącznie jako obiekt JSON z dwoma kluczami:
    1. 'evaluations': tablica z ocenami i krótkimi uzasadnieniami dla KAŻDEGO ID z listy kryteriów
    2. 'summary': krótkie podsumowanie (2-3 zdania) dlaczego kandydat pasuje do stanowiska (wymień mocne strony i luki)
    
    Przykład:
    {{
        "evaluations": [{{"id": 1, "score": 0.8, "justification": "Ma 3 lata stażu w dziale X."}}],
        "summary": "Kandydat posiada odpowiednie doświadczenie w sprzedaży i obsłudze klientów. Brakuje mu jednak doświadczenia z kasą fiskalną, co może wymagać dodatkowego szkolenia."
    }}
    """

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        result = _evaluate_match_heuristic(candidate_data, job_offer_data)
        result["message"] = "GROQ_API_KEY not set, using heuristic fallback"
        return result

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
        summary_from_llm = result_data.get("summary", "Brak podsumowania od modelu AI.")
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
            "evaluations": final_evaluations,
            "summary": summary_from_llm,
            "source": "llm",
        }
            
    except Exception as e:
        print(f"LLM Error: {e}")
        result = _evaluate_match_heuristic(candidate_data, job_offer_data)
        result["message"] = "LLM failed, using heuristic fallback"
        return result
