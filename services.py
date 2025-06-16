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
    model_name="gemini-2.5-flash-preview-05-20", # Use the latest, most capable model
    generation_config=generation_config,
    safety_settings=safety_settings
)

# --- Prompts ---
SUMMARY_PROMPT_TEMPLATE = """
You are a world-class AI research analyst. Your task is to analyze the provided text from an AI research paper or blog post and generate a structured, insightful summary.

**Instructions:**
1.  Read the provided title and abstract/content carefully.
2.  Identify the core problem, the proposed solution, the key results, and the potential impact.
3.  Synthesize this information into the specified JSON format. Be concise but informative.
4.  The title must be exactly as provided.
5.  All fields in the JSON object are mandatory.
6.  It is critical for my application that you strictly adhere to the provided JSON schema and include all fields.

**Title:**
{title}

**Content for Analysis:**
---
{content_text}
---

**Output Schema (JSON):**
{{
  "title": "{title}",
  "summary_what_is_new": "A single, compelling paragraph explaining the core innovation or breakthrough.",
  "summary_how_it_works": "A slightly more detailed but easy-to-understand explanation of the methodology or technology.",
  "summary_why_it_matters": "A paragraph explaining the potential impact on the AI field, specific industries, or humanity.",
  "keywords": ["An", "array", "of", "5-7", "highly", "relevant", "keywords"]
}}
"""

RANKING_PROMPT_TEMPLATE = """
You are an expert committee of AI researchers, venture capitalists, and ethicists.
Your task is to provide a multi-faceted score for the following AI breakthrough based on its summary.

**Instructions:**
1.  Review the provided summary JSON.
2.  For each category, provide a score from 1 to 10 and a concise, well-reasoned justification.
3.  The `overall_importance_score` should be a weighted consideration of the other factors, representing its total significance. Do not just average them. Consider novelty and influence more heavily.
4.  Output a single, valid JSON object with the exact schema provided.
5.  It is critical for my application that you strictly adhere to the provided JSON schema and include all fields.

**Summary for Scoring:**
---
{summary_json}
---

**Output Schema (JSON):**
{{
  "scores": {{
    "breakthrough_novelty": {{ "score": "[1-10]", "justification": "Justification for the novelty score." }},
    "human_impact": {{ "score": "[1-10]", "justification": "Justification for the human impact score." }},
    "field_influence": {{ "score": "[1-10]", "justification": "Justification for the field influence score." }},
    "technical_maturity": {{ "score": "[1-10]", "justification": "Justification for the technical maturity score." }}
  }},
  "overall_importance_score": "[A single floating-point number from 1.0 to 10.0, e.g., 8.7]",
  "overall_importance_justification": "A final synthesis of why this breakthrough is or isn't important, considering all factors."
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

def analyze_and_rank_progress(title: str, content_text: str):
    """
    Performs a two-step AI analysis. Now using the robust JSON cleaner.
    """
    print(f"SERVICES: Starting analysis for '{title}'")
    
    # Step 1: Summarization
    try:
        summary_prompt = SUMMARY_PROMPT_TEMPLATE.format(title=title, content_text=content_text)
        summary_response = model.generate_content(summary_prompt)
        summary_data = clean_json_response(summary_response.text)
        if not summary_data:
            raise ValueError("Cleaned summary JSON is None.")
    except Exception as e:
        print(f"SERVICES: ERROR in summarization step for '{title}': {e}")
        return None

    # Step 2: Ranking
    try:
        summary_json_str = json.dumps(summary_data, indent=2)
        ranking_prompt = RANKING_PROMPT_TEMPLATE.format(summary_json=summary_json_str)
        ranking_response = model.generate_content(ranking_prompt)
        ranking_data = clean_json_response(ranking_response.text)
        if not ranking_data:
            raise ValueError("Cleaned ranking JSON is None.")
    except Exception as e:
        print(f"SERVICES: ERROR in ranking step for '{title}': {e}")
        return None

    final_result = {**summary_data, **ranking_data}
    return final_result