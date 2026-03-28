import json
import os
from app.services.llm_match import evaluate_match_with_llm

# Eksportujemy klucz dla pewności w tym skrypcie testowym
os.environ["GROQ_API_KEY"] = "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"

# Przykładowy kandydat
mock_candidate = {
    "doswiadczenie": "5 lat pracy jako kierowca C+E na trasach międzynarodowych. Znajomość dokumentacji celnej.",
    "skills": "Punktualność, obsługa tachografu",
    "languages": "Angielski A2, Niemiecki A1",
    "preferencje": "Praca od poniedziałku do piątku (weekendy w domu)",
    "miasto": "Bydgoszcz",
    "wojewodztwo": "Kujawsko-Pomorskie",
    "niepelnosprawnosc": "Brak"
}

# Przykładowa oferta pracy
mock_job_offer = {
    "criteria": [
        {"id": 1, "description": "Prawo jazdy kat. C+E oraz doświadczenie w trasach", "weight": 10},
        {"id": 2, "description": "Komunikatywny język angielski (min. B1)", "weight": 4},
        {"id": 3, "description": "Gotowość do pracy w weekendy", "weight": 8}
    ]
}

print("Wysyłam zapytanie do modelu LLM (Groq Llama 3)... Oczekuj na wynik.\n")

result = evaluate_match_with_llm(mock_candidate, mock_job_offer)

print("\n--- WYNIK DOPASOWANIA ---")
print(json.dumps(result, indent=2, ensure_ascii=False))
