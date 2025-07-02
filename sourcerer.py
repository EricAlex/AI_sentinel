# sourcerer.py

import os
import json
import traceback
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from googlesearch import search

import google.generativeai as genai
from celery_app import celery
from database import SessionLocal, ParserProposal, Source, create_or_update_custom_parser, add_new_source, create_tenant, get_tenant_by_id # Import the new function
from parsers import DEFAULT_PARSERS # Use DEFAULT_PARSERS instead of PARSER_MAP
from dotenv import load_dotenv

# --- NEW: Define a constant for shared tenant ID ---
SHARED_TENANT_ID = "system_shared_sources" # Or a specific UUID for shared resources
# ---------------------------------------------------

# --- NEW: Ensure the shared tenant exists ---
def ensure_shared_tenant_exists():
    db = SessionLocal()
    try:
        tenant = get_tenant_by_id(SHARED_TENANT_ID)
        if not tenant:
            print(f"SOURCERER: Creating shared system tenant: {SHARED_TENANT_ID}")
            create_tenant(name="System Shared Sources", description="Tenant for globally shared content and configurations.", id=SHARED_TENANT_ID)
    finally:
        db.close()

ensure_shared_tenant_exists()

# --- Standard Request Headers to mimic a browser ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Connection': 'keep-alive',
}
# ---------------------------------------------

# --- Configuration ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    # This service is non-essential, so we can disable it if the key is missing
    print("SOURCERER: WARNING - GOOGLE_API_KEY not found. Sourcerer tasks will be disabled.")
    genai_model = None
else:
    genai.configure(api_key=API_KEY)
    genai_model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={"response_mime_type": "application/json"}
    )

# --- NEW, POWERFUL HEALER PROMPT ---
HEALER_PROMPT_TEMPLATE = """
You are an expert web scraping engineer specializing in Python and BeautifulSoup.
A parser for the source '{source_name}' at URL '{url}' has failed. I need you to write a new, robust Python parser function.

**Instructions:**
1.  Analyze the provided HTML source code snapshot. Focus on identifying consistent patterns for articles.
2.  Identify the main repeating container element for each article/post.
3.  For each post, find the selectors for:
    - The full URL to the article.
    - The title of the article.
    - A brief abstract or summary.
4.  Write a **complete, standalone Python function** with the exact signature: `def custom_parse(url: str, source_name: str, max_results=8) -> list:`.
5.  The function must import `requests`, `BeautifulSoup`, `datetime`, and `urljoin` internally.
6.  The function must return a list of dictionaries, each with keys: "entry_id", "title", "abstract", "authors", "published_date", "url", "source".
7.  Handle potential errors gracefully with `try/except` blocks inside the loop for each article, especially for elements that might be missing.
8.  Your entire response must be ONLY the Python code for the function, enclosed in ```python ... ```. Do not add any other text, explanation, or introductions.

**URL of Failing Source:** {url}

**HTML Content (snapshot):**
---
{html_content}
---
"""

# --- A prompt template specifically for providing feedback ---
FEEDBACK_PROMPT_TEMPLATE = """
You are an expert web scraping engineer performing a debugging task.
Your previous attempt to write a Python parser for the source '{source_name}' at URL '{url}' failed.

**Your previous code:**
```python
{previous_code}
```

**Reason for failure:**
{failure_reason}

**Your Task:**
Analyze your previous code and the failure reason. Identify your mistake (e.g., wrong CSS selectors, incorrect logic, missing error handling) and write a **new, corrected, complete Python function**.

**Instructions:**
1.  Do NOT simply repeat the old code. Propose a different, more robust strategy if the previous one was flawed.
2.  Look for alternative, more stable CSS classes, HTML tags, or structural patterns in the HTML.
3.  Ensure the function has the exact signature: `def custom_parse(url: str, source_name: str, max_results=8) -> list:`.
4.  Your entire response must be ONLY the Python code for the function, enclosed in ```python ... ```. Do not add any other text, explanation, or introductions.

**Original HTML Content (for re-analysis):**
---
{html_content}
---
"""

@celery.task(name="sourcerer.attempt_heal_parser", bind=True, max_retries=1)
def attempt_heal_parser(self, source_id: int, tenant_id: str):
    """
    Iteratively attempts to fix a parser by providing feedback to the AI.
    """
    if not genai_model:
        return f"Healer skipped for source ID {source_id}: Gemini API not configured."

    db = SessionLocal()
    source = db.query(Source).get(source_id)
    if not source:
        db.close()
        return f"Healer skipped: Source ID {source_id} not found."
    
    # For custom parsers, we'll use a generic name 'custom_parse'
    func_name = "custom_parse"

    print(f"HEALER: Starting healing loop for '{source.name}' ({func_name}) for tenant {tenant_id}")

    try:
        response = requests.get(source.url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        html_content = response.text
    except requests.RequestException as e:
        db.close()
        return f"Healer failed: Could not fetch HTML from {source.url}. Error: {e}"

    max_attempts = 5
    last_attempted_code = ""
    last_failure_reason = ""

    for attempt in range(1, max_attempts + 1):
        print(f"--- HEALER ATTEMPT #{attempt} for {source.name} (tenant {tenant_id}) ---")
        
        if attempt == 1:
            prompt = HEALER_PROMPT_TEMPLATE.format(
                source_name=source.name, url=source.url, function_name=func_name,
                html_content=html_content[:25000]
            )
        else:
            prompt = FEEDBACK_PROMPT_TEMPLATE.format(
                source_name=source.name, url=source.url, function_name=func_name,
                previous_code=last_attempted_code, failure_reason=last_failure_reason,
                html_content=html_content[:25000]
            )
        
        try:
            ai_response = genai_model.generate_content(prompt)
            ai_code = ai_response.text.strip().replace("```python", "").replace("```", "").strip()
            last_attempted_code = ai_code
        except Exception as e:
            last_failure_reason = f"AI code generation failed with an API error: {e}"
            print(f"HEALER: AI generation failed on attempt {attempt}: {e}")
            time.sleep(10)
            continue

        print(f"HEALER: Validating AI-generated code (Attempt #{attempt})...")
        try:
            temp_namespace = {}
            # Ensure necessary imports are available for exec
            exec("import requests; from bs4 import BeautifulSoup; from datetime import datetime; from urllib.parse import urljoin", globals(), temp_namespace)
            exec(ai_code, globals(), temp_namespace) # Pass globals() to provide access to imported modules
            new_parser_func = temp_namespace.get(func_name) # Use func_name for the expected function name

            if not callable(new_parser_func):
                raise ValueError("AI did not generate a callable function.")
            
            validation_results = new_parser_func(url=source.url, source_name=source.name)
            
            if not isinstance(validation_results, list):
                raise TypeError("Generated function did not return a list.")
            
            if not validation_results:
                 raise ValueError("Validation successful, but the parser returned an empty list. The selectors are likely still incorrect.")

            if not all(k in validation_results[0] for k in ["title", "url", "entry_id"]):
                 raise ValueError("Generated function's output is missing required keys.")

            print(f"HEALER: VALIDATION SUCCESS on attempt #{attempt} for '{source.name}'. Found {len(validation_results)} items.")
            
            # Store the custom parser in the database
            create_or_update_custom_parser(tenant_id, source.id, ai_code)

            # Optionally, record the proposal for history/review
            new_proposal = ParserProposal(
                tenant_id=tenant_id, # Store tenant_id with proposal
                source_id=source.id, proposed_code=ai_code,
                validation_output_sample=validation_results[:3],
                status='approved' # Mark as approved since it's applied
            )
            db.add(new_proposal)
            db.commit()
            db.close()
            return f"Successfully created and applied a custom parser for '{source.name}' for tenant {tenant_id} after {attempt} attempts."

        except Exception as e:
            print(f"HEALER: VALIDATION FAILED on attempt #{attempt}. Error: {e}")
            last_failure_reason = f"The code executed but failed with the following error traceback:\n{traceback.format_exc()}"
            time.sleep(5)
    
    db.close()
    return f"Healer failed for '{source.name}' (tenant {tenant_id}) after {max_attempts} attempts. Manual review required."

# --- Prompt for Source Validation ---
SOURCERER_PROMPT = """
You are an AI research analyst responsible for curating our data sources.
Evaluate the given URL and determine if it points to a high-quality, English-language blog or news site that regularly publishes technical content about AI, machine learning, or data science breakthroughs.

**Criteria for High-Quality Source:**
-   **Regularly updated:** Publishes new content at least monthly.
-   **Technical depth:** Content goes beyond superficial news, offering insights, research summaries, or technical explanations.
-   **Focus on AI/ML/Data Science:** Primarily dedicated to these fields, not just general tech.
-   **Reputable:** From established research labs, academic institutions, or well-regarded independent experts.

**Do NOT approve:**
- Corporate product marketing pages.
- General tech news sites that only occasionally mention AI.
- Individual researcher homepages or university department pages.
- Social media profiles or forums.
- Sites with very infrequent updates (less than monthly).

**Strongly approve:**
- Dedicated research blogs from major AI labs (e.g., DeepMind, OpenAI, Google AI).
- High-quality, independent blogs focused on explaining AI research (e.g., The Gradient, Towards Data Science).
- The AI-specific section of a major tech publication (e.g., MIT Technology Review's AI section, Synced Review).

**URL to Analyze:** "{url}"

**Output Schema (JSON):**
{{
  "is_high_quality_source": boolean,
  "reasoning": "A concise, one-sentence justification for your decision (e.g., 'Regularly updated with in-depth ML research articles.').",
  "source_name": "The proper, official name of the publication (e.g., 'The Gradient', 'Google AI Blog').",
  "source_type": "One of ['blog', 'news', 'research_portal', 'other']"
}}
"""

@celery.task(name="sourcerer.find_new_sources")
def find_new_sources():
    """
    A Celery task that searches Google for new AI blogs and validates them with Gemini.
    These sources will be marked as shared.
    """
    if not genai_model:
        return "Sourcerer task skipped: Gemini API key not configured."

    print("SOURCERER: Starting cycle to find new AI sources.")
    
    # Use a variety of search queries to get diverse results
    queries = [
        "top AI research blogs 2024",
        "best machine learning blogs for researchers",
        "new large language model announcements blog"
    ]
    
    potential_urls = set()
    for query in queries:
        try:
            for url in search(query, num_results=10, sleep_interval=2):
                potential_urls.add(url)
        except Exception as e:
            print(f"SOURCERER: WARN - Google search failed for query '{query}': {e}")
            continue

    db = SessionLocal()
    try:
        # Get all existing URLs to avoid re-processing
        # Need to consider both shared and tenant-specific sources for uniqueness check
        existing_urls = {s.url for s in db.query(Source.url).all()}
    finally:
        db.close()
    
    new_sources_added = 0
    for url in potential_urls:
        if url in existing_urls:
            continue
        
        print(f"SOURCERER: Evaluating potential new source: {url}")
        try:
            response = genai_model.generate_content(SOURCERER_PROMPT.format(url=url))
            result = json.loads(response.text.strip())
            
            if result.get("is_high_quality_source"):
                print(f"SOURCERER: VALIDATED new source '{result.get('source_name')}' at {url}")
                # Use add_new_source with is_shared=True and the SHARED_TENANT_ID
                new_source = add_new_source(
                    name=result.get('source_name'),
                    url=url,
                    source_type=result.get('source_type'),
                    tenant_id=SHARED_TENANT_ID, # Assign to the shared tenant
                    is_shared=True # Mark as shared
                )
                if new_source:
                    new_sources_added += 1

        except Exception as e:
            print(f"SOURCERER: Could not process URL {url}. Reason: {e}")
            
    return f"Sourcerer cycle complete. Added {new_sources_added} new shared sources to the database."
