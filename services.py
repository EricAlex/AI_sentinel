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
You are an expert AI research analyst. Your task is to analyze the provided text and return a structured JSON object.

**Instructions:**
1.  **Analyze:** Carefully read the provided English title and content.
2.  **Summarize:** Generate concise and clear summaries for `what_is_new`, `how_it_works`, and `why_it_matters` in English.
3.  **Rank:** Provide a numeric score from 1 to 10 for each of the four ranking criteria. Provide a brief justification for each score.
4.  **Synthesize:** Write a final `overall_importance_justification` that synthesizes your analysis and the individual score justifications.
5.  **Translate:** Translate the `title` and all summary/justification fields into the target languages specified (`zh`).
6.  **Keywords:** Extract 5-7 relevant English keywords.
7.  **Format:** Your entire response must be a single, valid JSON object. All fields are mandatory. If you cannot determine a value for a field from the text, use "N/A".

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
    "what_is_new": "A concise paragraph in English explaining the core innovation.",
    "how_it_works": "A clear, easy-to-understand explanation in English of the methodology.",
    "why_it_matters": "A paragraph in English explaining the potential impact and significance.",
    "overall_importance_justification": "A final synthesis in English of why this breakthrough is important, summarizing the key ranking factors."
  }},
  "zh": {{
    "title": "一个翻译成简体中文的准确标题。",
    "what_is_new": "一个引人注目的段落，用简体中文解释核心创新。",
    "how_it_works": "一个易于理解的解释，用简体中文说明其方法论。",
    "why_it_matters": "一个段落，用简体中文解释其潜在影响。",
    "overall_importance_justification": "一段最终综合陈述，用简体中文说明此突破为何重要。"
  }},
  "keywords": ["list", "of", "5-7", "English", "keywords"],
  "ranking": {{
    "scores": {{
      "breakthrough_novelty": {{ "score": "[1-10]", "justification": "Brief justification in English." }},
      "human_impact": {{ "score": "[1-10]", "justification": "Brief justification in English." }},
      "field_influence": {{ "score": "[1-10]", "justification": "Brief justification in English." }},
      "technical_maturity": {{ "score": "[1-10]", "justification": "Brief justification in English." }}
    }}
  }}
}}
"""

def clean_json_response(response_text):
    """
    Cleans the Gemini response to extract a valid JSON object,
    even if it's embedded in markdown or has trailing commas.
    """
    # Find the start and end of the JSON block, assuming it's the primary content
    # This regex is more specific, looking for a JSON object that might be wrapped
    # in markdown code blocks (```json ... ```) or just stand alone.
    json_match = re.search(r'```json\s*(\{.*\})\s*```|(\{.*\})', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1) or json_match.group(2)
    else:
        print("SERVICES: ERROR - No JSON object found in the response.")
        return None
    
    try:
        # The primary method: try to load the JSON directly
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"SERVICES: WARN - Initial JSON decode failed: {e}. Attempting to fix common errors.")
        # Attempt to fix common errors, like trailing commas and invalid escape sequences
        try:
            # Remove trailing commas from objects and arrays
            json_str_fixed = re.sub(r',\s*([}\]])', r'\1', json_str)
            # Replace single backslashes that are not part of a valid escape sequence
            # This is a heuristic and might need adjustment based on specific invalid sequences
            json_str_fixed = json_str_fixed.replace('\\', '\\\\') # Double backslashes
            json_str_fixed = json_str_fixed.replace('\\n', '\n') # Fix escaped newlines
            json_str_fixed = json_str_fixed.replace('\\t', '\t') # Fix escaped tabs
            return json.loads(json_str_fixed)
        except json.JSONDecodeError as e2:
            print(f"SERVICES: ERROR - Failed to decode JSON even after fixing common errors: {e2}")
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

        # --- Add manual calculation of overall_importance_score ---
        try:
            scores = analysis_data.get("ranking", {}).get("scores", {})
            if scores:
                total_score = 0
                score_count = 0
                for key in ["breakthrough_novelty", "human_impact", "field_influence", "technical_maturity"]:
                    # Use .get() to avoid KeyError if a score is missing
                    score_value = scores.get(key, {}).get("score")
                    if score_value:
                        try:
                            total_score += float(score_value)
                            score_count += 1
                        except (ValueError, TypeError):
                            print(f"SERVICES: WARN - Could not convert score '{score_value}' to float for key '{key}'.")
                
                if score_count > 0:
                    average_score = total_score / score_count
                    # Add the calculated score to the dictionary
                    analysis_data["ranking"]["overall_importance_score"] = round(average_score, 2)
                    print(f"SERVICES: Calculated overall_importance_score: {average_score:.2f}")
                else:
                    # Handle case where no valid scores were found
                    analysis_data["ranking"]["overall_importance_score"] = 0.0
                    print("SERVICES: WARN - No valid scores found to calculate average.")
        except Exception as e:
            print(f"SERVICES: ERROR - Failed to calculate overall_importance_score: {e}")
            # If calculation fails, ensure the key exists with a default value
            if "ranking" not in analysis_data:
                analysis_data["ranking"] = {}
            analysis_data["ranking"]["overall_importance_score"] = 0.0
        # --- End of manual calculation ---
            
        print(f"SERVICES: Unified analysis complete for '{title}'")
        return analysis_data
        
    except (ValueError, json.JSONDecodeError, genai.APIError) as e:
        print(f"SERVICES: ERROR in unified analysis step for '{title}': {e}")
        return None
    except Exception as e:
        print(f"SERVICES: An unexpected error occurred during unified analysis for '{title}': {e}")
        return None