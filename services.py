import os
import json
from database import SessionLocal, TenantLLMConfig, get_llm_config_for_tenant, create_or_update_llm_config
from typing import Optional
import google.generativeai as genai
from openai import OpenAI

class TenantConfigService:
    @staticmethod
    def get_llm_config(tenant_id: str) -> Optional[TenantLLMConfig]:
        return get_llm_config_for_tenant(tenant_id)

    @staticmethod
    def create_or_update_llm_config(tenant_id: str, llm_provider: str, llm_model_name: str, api_key: str, base_url: Optional[str] = None, custom_settings: Optional[dict] = None) -> Optional[TenantLLMConfig]:
        return create_or_update_llm_config(tenant_id, llm_provider, llm_model_name, api_key, base_url, custom_settings)

# --- LLM Client Initialization (Dynamic) ---
def get_llm_client(tenant_id: str):
    llm_config = TenantConfigService.get_llm_config(tenant_id)

    if not llm_config:
        # Fallback to default if no tenant-specific config is found
        print(f"No LLM config found for tenant {tenant_id}. Using default Google Gemini.")
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        return genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )

    if llm_config.llm_provider == "google":
        genai.configure(api_key=llm_config.get_api_key())
        return genai.GenerativeModel(
            model_name=llm_config.llm_model_name,
            generation_config={"response_mime_type": "application/json"}
        )
    elif llm_config.llm_provider == "openai":
        return OpenAI(
            api_key=llm_config.get_api_key(),
            base_url=llm_config.base_url if llm_config.base_url else None
        )
    elif llm_config.llm_provider == "huggingface":
        # Hugging Face models typically require a different approach (e.g., Inference API)
        # This is a placeholder. You'd integrate a Hugging Face client here.
        raise NotImplementedError("Hugging Face LLM integration is not yet implemented.")
    else:
        raise ValueError(f"Unsupported LLM provider: {llm_config.llm_provider}")

# --- AI Analysis Function (now uses dynamic LLM client) ---
def analyze_rank_and_translate(title: str, abstract: str, tenant_id: str):
    """
    Analyzes a research paper's title and abstract to generate a structured
    JSON output containing multi-lingual summaries, keywords, and a detailed
    importance ranking.

    This function now includes a more robust and detailed prompt to ensure
    the AI returns all required fields, including a full score breakdown.
    The overall score is calculated downstream, not requested from the AI.
    """
    llm_client = get_llm_client(tenant_id)

    # The overall_importance_score is removed from the prompt, but the
    # justification is kept for UI display.
    prompt = f'''Analyze the following research paper/article and provide a comprehensive analysis in a structured JSON format.

Title: {title}
Abstract: {abstract}

Your output MUST be a single, valid JSON object. Do not include any text or formatting before or after the JSON.
The JSON object must follow this exact structure, including all fields:
{{
  "en": {{
    "title": "A concise, translated title in English.",
    "what_is_new": "A detailed summary of the key innovations and findings presented in the paper.",
    "why_it_matters": "A clear explanation of the potential impact and significance of this research.",
    "how_it_works": "A simplified explanation of the methodology or technology described."
  }},
  "zh": {{
    "title": "一个简洁的中文翻译标题。",
    "what_is_new": "关于论文中提出的关键创新和发现的详细中文摘要。",
    "why_it_matters": "关于这项研究的潜在影响和重要性的清晰中文解释。",
    "how_it_works": "对所描述方法或技术的简化中文说明。"
  }},
  "keywords": [
    "keyword1",
    "keyword2",
    "keyword3"
  ],
  "ranking": {{
    "overall_importance_justification": "A detailed justification for the overall importance, considering all factors. This will be displayed in the UI.",
    "scores": {{
      "breakthrough_novelty": {{
        "score": "A score from 0 to 10 for novelty.",
        "justification": "Justification for the novelty score."
      }},
      "human_impact": {{
        "score": "A score from 0 to 10 for human impact.",
        "justification": "Justification for the human impact score."
      }},
      "field_influence": {{
        "score": "A score from 0 to 10 for field influence.",
        "justification": "Justification for the field influence score."
      }},
      "technical_maturity": {{
        "score": "A score from 0 to 10 for technical maturity.",
        "justification": "Justification for the technical maturity score."
      }}
    }}
  }}
}}
'''

    try:
        if isinstance(llm_client, genai.GenerativeModel):
            # For Gemini, the prompt is sent directly.
            response = llm_client.generate_content(prompt)
            # It's good practice to add a print statement for debugging the raw response
            print(f"DEBUG: Raw Gemini response: {response.text}")
            return json.loads(response.text)
        
        elif isinstance(llm_client, OpenAI):
            # For OpenAI, the prompt is part of the messages list.
            chat_completion = llm_client.chat.completions.create(
                model=getattr(llm_client, 'model', 'gpt-4-turbo'), # Safely get model
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            response_content = chat_completion.choices[0].message.content
            # Debugging for OpenAI response
            print(f"DEBUG: Raw OpenAI response: {response_content}")
            return json.loads(response_content)
        
        else:
            print(f"Unsupported LLM client type: {type(llm_client)}")
            raise ValueError("Unsupported LLM client type.")
            
    except json.JSONDecodeError as e:
        # This error is crucial for debugging invalid JSON from the LLM
        print(f"SERVICES: FATAL ERROR - Failed to decode JSON from LLM response. Error: {e}")
        # Optionally, log the raw response text that failed to parse
        raw_response = "Unknown"
        if 'response' in locals() and hasattr(response, 'text'):
            raw_response = response.text
        elif 'response_content' in locals():
            raw_response = response_content
        print(f"SERVICES: Raw failing response: {raw_response}")
        return None # Return None to indicate failure
        
    except Exception as e:
        print(f"SERVICES: An unexpected error occurred during LLM analysis: {e}")
        return None