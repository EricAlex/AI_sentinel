# services.py

import os
import json
import re
import google.generativeai as genai
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in .env file.")

genai.configure(api_key=API_KEY)

# These settings are a good starting point for consistent JSON output
generation_config = {
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 32,
    "max_output_tokens": 65536,
    "response_mime_type": "application/json",
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash", # Use the latest, most capable model
    generation_config=generation_config,
    safety_settings=safety_settings
)

# --- Prompts ---
UNIFIED_PROMPT_TEMPLATE = """
You are a world-class, multi-lingual AI research analyst. Your task is to perform a comprehensive analysis of the provided text and return a single, structured JSON object.

**Instructions:**
1.  **Analyze:** Read the provided English title and content to understand the core innovation, methodology, results, and impact.
2.  **Summarize & Translate:** Generate the content for the `en` (English) object first. Then, translate the `title`, `what_is_new`, `how_it_works`, `why_it_matters`, and `overall_importance_justification` fields accurately and naturally into each of the specified target languages: `zh` (Simplified Chinese).
3.  **Rank:** Based on your English analysis, provide the numeric scores. Justifications should also be translated.
4.  **Format:** Your entire response must be a single, valid JSON object adhering strictly to the schema below. All fields are mandatory.

**Original English Title:**
{title}

**Content for Analysis:**
---
{content_text}
---

**Output Schema (JSON):**
{{
  "en": {{
    "title": "{title}",
    "what_is_new": "A compelling paragraph in English explaining the core innovation.",
    "how_it_works": "An easy-to-understand explanation in English of the methodology.",
    "why_it_matters": "A paragraph in English explaining the potential impact.",
    "overall_importance_justification": "A final synthesis in English of why this breakthrough is important."
  }},
  "zh": {{
    "title": "一个翻译成简体中文的准确标题。",
    "what_is_new": "一个引人注目的段落，用简体中文解释核心创新。",
    "how_it_works": "一个易于理解的解释，用简体中文说明其方法论。",
    "why_it_matters": "一个段落，用简体中文解释其潜在影响。",
    "overall_importance_justification": "一段最终综合陈述，用简体中文说明此突破为何重要。"
  }},
  "keywords": ["An", "array", "of", "5-7", "English", "keywords"],
  "ranking": {{
    "scores": {{
      "breakthrough_novelty": {{ "score": "[1-10]", "justification": "Justification in English." }},
      "human_impact": {{ "score": "[1-10]", "justification": "Justification in English." }},
      "field_influence": {{ "score": "[1-10]", "justification": "Justification in English." }},
      "technical_maturity": {{ "score": "[1-10]", "justification": "Justification in English." }}
    }},
    "overall_importance_score": "[A single floating-point number from 1.0 to 10.0, e.g., 8.7]"
  }}
}}
"""

def clean_json_response(response_text):
    """
    Cleans the Gemini response to extract a valid JSON object,
    even if it's embedded in markdown or has trailing commas.
    """
    # Find the start and end of the JSON block using curly braces
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if not json_match:
        print("SERVICES: ERROR - No JSON object found in the response.")
        return None
    
    json_str = json_match.group(0)
    
    try:
        # The primary method: try to load the JSON directly
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"SERVICES: WARN - Initial JSON decode failed: {e}. Attempting to fix common errors.")
        # Attempt to fix common errors, like trailing commas
        # This is a common issue with LLM-generated JSON
        try:
            # Remove trailing commas from objects and arrays
            json_str_fixed = re.sub(r',\s*([}\]])', r'\1', json_str)
            return json.loads(json_str_fixed)
        except json.JSONDecodeError as e2:
            print(f"SERVICES: ERROR - Failed to decode JSON even after fixing trailing commas: {e2}")
            print(f"--- FAULTY JSON STRING --- \n{json_str}\n--------------------------")
            return None

def analyze_rank_and_translate(title: str, content_text: str):
    """
    Performs summarization, ranking, and translation in a single API call.

    Returns:
        A single, comprehensive dictionary, or None on failure.
    """
    print(f"SERVICES: Starting unified analysis for '{title}'")
    
    try:
        prompt = UNIFIED_PROMPT_TEMPLATE.format(title=title, content_text=content_text)
        response = model.generate_content(prompt)
        analysis_data = clean_json_response(response.text)
        
        if not analysis_data:
            raise ValueError("Cleaned JSON from Gemini is None.")
            
        print(f"SERVICES: Unified analysis complete for '{title}'")
        return analysis_data
        
    except Exception as e:
        print(f"SERVICES: ERROR in unified analysis step for '{title}': {e}")
        return None