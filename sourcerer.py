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
from database import SessionLocal, ParserProposal, Source
from parsers import PARSER_MAP, HEADERS
from dotenv import load_dotenv



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
You are an expert web scraping engineer. A parser for '{source_name}' at '{url}' has failed. Write a new, robust Python parser function.

**Instructions:**
1.  Analyze the provided HTML to identify the main repeating container for each article.
2.  For each article, find the selectors for the full URL, title, and a brief abstract.
3.  Write a complete, standalone Python function `def {function_name}(url: str, source_name: str, max_results=8) -> list:`.
4.  The function must import `requests`, `BeautifulSoup`, `datetime`, and `urljoin`.
5.  Return a list of dictionaries, each with keys: "entry_id", "title", "abstract", "authors", "published_date", "url", "source".
6.  Use `try/except` blocks to handle errors gracefully.
7.  Your response must be ONLY the Python code for the function, enclosed in ```python ... ```.

**URL:** {url}
**HTML Content:**
---
{html_content}
---
"""

# --- A prompt template specifically for providing feedback ---
FEEDBACK_PROMPT_TEMPLATE = """
You are an expert web scraping engineer debugging a script. Your previous attempt to write a Python parser for '{source_name}' failed.

**Your previous code:**
```python
{previous_code}
```

**Failure reason:**
{failure_reason}

**Your Task:**
Analyze your previous code and the failure reason. Write a new, corrected, complete Python function.

**Instructions:**
1.  Propose a different strategy; do not repeat the old code.
2.  Find alternative, more stable CSS classes or HTML tags.
3.  Ensure the function signature is `def {function_name}(url: str, source_name: str, max_results=8) -> list:`.
4.  Your response must be ONLY the Python code for the function, enclosed in ```python ... ```.

**Original HTML Content (for re-analysis):**
---
{html_content}
---
"""

@celery.task(name="sourcerer.attempt_heal_parser", bind=True, max_retries=5)
def attempt_heal_parser(self, source_id: int):
    """
    Iteratively attempts to fix a parser by providing feedback to the AI.
    """
    if not genai_model:
        return f"Healer skipped for source ID {source_id}: Gemini API not configured."

    with SessionLocal() as db:
        source = db.query(Source).get(source_id)
        if not source:
            return f"Healer skipped: Source ID {source_id} not found."
        
        func_name = None
        for name, func in PARSER_MAP.items():
            if name == source.source_type:
                func_name = func.__name__
                break
                
        if not func_name:
            return f"Healer skipped: No parser function found for source_type '{source.source_type}'."

        print(f"HEALER: Starting healing loop for '{source.name}' ({func_name})")

        try:
            response = requests.get(source.url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            html_content = response.text
        except requests.RequestException as e:
            return f"Healer failed: Could not fetch HTML from {source.url}. Error: {e}"

        max_attempts = 5
        last_attempted_code = ""
        last_failure_reason = ""

        for attempt in range(1, max_attempts + 1):
            print(f"--- HEALER ATTEMPT #{attempt} for {source.name} ---")
            
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
                exec(ai_code, globals(), temp_namespace) # Pass globals() to provide access to imported modules
                new_parser_func = temp_namespace.get(func_name)

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
                
                new_proposal = ParserProposal(
                    source_id=source.id, proposed_code=ai_code,
                    validation_output_sample=validation_results[:3]
                )
                db.add(new_proposal)
                db.commit()
                return f"Successfully created a healing proposal for '{source.name}' after {attempt} attempts."

            except Exception as e:
                print(f"HEALER: VALIDATION FAILED on attempt #{attempt}. Error: {e}")
                last_failure_reason = f"The code executed but failed with the following error traceback:\n{traceback.format_exc()}"
                time.sleep(5)
        
        return f"Healer failed for '{source.name}' after {max_attempts} attempts. Manual review required."

@celery.task(name="sourcerer.apply_parser_fix")
def apply_parser_fix(proposal_id: int):
    """
    Reads an approved proposal from the DB and programmatically
    updates the parsers.py file.
    """
    with SessionLocal() as db:
        proposal = db.query(ParserProposal).get(proposal_id)
        if not proposal or proposal.status != 'pending_review':
            return "Apply fix failed: Proposal not found or not pending."

        source = db.query(Source).get(proposal.source_id)
        func_name_to_replace = None
        for name, func in PARSER_MAP.items():
            if name == source.source_type:
                func_name_to_replace = func.__name__
                break
                
        if not func_name_to_replace:
            return f"Apply fix failed: Could not find function for source_type '{source.source_type}'"

        print(f"APPLYING FIX: Replacing function '{func_name_to_replace}' in parsers.py...")

        try:
            with open('/app/parsers.py', 'r') as f:
                lines = f.readlines()
            
            # Find the start and end of the function to replace
            start_index, end_index = -1, -1
            for i, line in enumerate(lines):
                if line.strip().startswith(f"def {func_name_to_replace}("):
                    start_index = i
                elif start_index != -1 and line.strip().startswith("def "):
                    end_index = i
                    break
            
            if start_index == -1:
                raise FileNotFoundError(f"Could not find function {func_name_to_replace} to replace.")
            
            # If it's the last function in the file
            if end_index == -1:
                end_index = len(lines)

            # Reconstruct the file with the new code
            new_code_lines = proposal.proposed_code.split('\n')
            # Add a newline for proper spacing
            new_code_with_spacing = [line + '\n' for line in new_code_lines] + ['\n']

            final_lines = lines[:start_index] + new_code_with_spacing + lines[end_index:]

            with open('/app/parsers.py', 'w') as f:
                f.writelines(final_lines)
                
            # Update the proposal status
            proposal.status = 'approved'
            db.commit()
            print(f"APPLYING FIX: Successfully updated parsers.py for '{source.name}'.")
            return f"Successfully applied fix for {source.name}."

        except Exception as e:
            proposal.status = 'apply_failed'
            db.commit()
            print(f"APPLYING FIX: ERROR while writing to parsers.py: {e}")
            return f"Failed to apply fix for {source.name}. Error: {e}"

# --- Prompt for Source Validation ---
SOURCERER_PROMPT = """
You are an AI research analyst curating data sources. Evaluate the given URL.

**Criteria:**
- **Approve:** High-quality, English-language blogs or news sites focused on technical AI, machine learning, or data science breakthroughs. Examples: research blogs from major AI labs, independent blogs explaining AI research, AI-specific sections of major tech publications.
- **Reject:** Corporate marketing pages, general tech news, personal homepages, social media, or forums.

**URL to Analyze:** "{url}"

**Output Schema (JSON):**
{{
  "is_high_quality_source": boolean,
  "reasoning": "A concise, one-sentence justification for your decision.",
  "source_name": "The proper name of the publication (e.g., 'The Gradient', 'Google AI Blog').",
  "source_type": "One of ['blog', 'news', 'other']"
}}
"""

@celery.task(name="sourcerer.find_new_sources")
def find_new_sources():
    """
    A Celery task that searches Google for new AI blogs and validates them with Gemini.
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
                new_source = Source(
                    name=result.get('source_name'),
                    url=url,
                    source_type=result.get('source_type'),
                    is_active=True # Add new sources as active by default
                )
                with SessionLocal() as db:
                    try:
                        db.add(new_source)
                        db.commit()
                        new_sources_added += 1
                    except IntegrityError:
                        db.rollback() # Handle rare race condition if URL was added in another process

        except Exception as e:
            print(f"SOURCERER: Could not process URL {url}. Reason: {e}")
            
    return f"Sourcerer cycle complete. Added {new_sources_added} new sources to the database."