# 🧠 The AI Progress Sentinel

**The AI Progress Sentinel is an automated, AI-powered application that discovers, analyzes, and ranks the latest breakthroughs in Artificial Intelligence.**

This system continuously scans a wide range of sources—from academic pre-print servers like arXiv to the official blogs of major AI labs—to ensure you never miss an important development. It uses the Google Gemini Pro model (or other configurable LLMs) to generate insightful, structured summaries and to score each breakthrough based on its novelty, potential impact, and influence on the field. All this information is presented in a clean, interactive, and searchable web dashboard built with Streamlit.

 
*(Note: You should replace this with a real screenshot of your app)*

---

## ✨ Features

*   **Multi-Tenant Architecture:** Supports multiple independent users (tenants), each with their own isolated data and customizable settings.
*   **Customizable LLM Settings per Tenant:** Each tenant can configure their preferred LLM provider (Google Gemini, OpenAI), model name, and API key, ensuring flexibility and cost control.
*   **Multi-Source Aggregation:** Continuously scrapes a curated and expandable list of sources, including:
    *   arXiv (cs.AI, cs.LG, cs.CV, etc.)
    *   Official AI Blogs (Microsoft Research, and others as they are maintained)
    *   Sources can be shared across all tenants or specific to an individual tenant.
*   **AI-Powered Summarization & Ranking:** Uses configurable LLMs to perform a two-step analysis on each item:
    1.  **Summarization:** Generates a structured summary explaining what's new, how it works, and why it matters.
    2.  **Ranking:** Scores the breakthrough on multiple axes (Novelty, Human Impact, Field Influence, Technical Maturity) with justifications.
*   **Semantic Search:** Powered by vector embeddings, allowing users to search for concepts and ideas, not just keywords (e.g., "alternatives to transformers").
*   **Interactive Dashboard:** A modern web UI built with Streamlit for intuitive filtering, sorting, and exploration of AI progress.
*   **Personalization:** Users can "follow" specific keywords or authors to create a personalized feed.
*   **Automated & Resilient:** Built on a production-grade, containerized architecture using Docker and Celery to handle background processing, task queuing, and automatic retries.
*   **AI-Driven Source Discovery:** A `sourcerer` service that periodically finds and validates new potential AI blogs to add to the ingestion pipeline (these are added as shared sources).
*   **Admin & Health Dashboard:** A dedicated dashboard for system administrators to monitor system health, service status, and manage shared sources. Tenant administrators can manage their tenant's specific LLM settings and sources.

---

## 🏗️ System Architecture

The application is built on a modern, decoupled, multi-service architecture, fully containerized with Docker for easy deployment and scalability.

 
*(Note: You should replace this with a real diagram if you have one)*

*   **Frontend (UI):** `Streamlit` provides the interactive user dashboard.
*   **Backend (API):** `FastAPI` serves as the main backend API, handling user authentication, data retrieval, and configuration management for tenants.
*   **Backend (Workers):** `Celery` manages a distributed task queue for all heavy processing (scraping, AI analysis), ensuring the UI remains fast and responsive.
*   **Message Broker:** `Redis` handles the task queue, mediating between the scraper/scheduler and the Celery workers.
*   **Scheduler:** `Celery Beat` with the `django-celery-beat` backend triggers recurring tasks like scraping and reporting.
*   **Relational Database:** `PostgreSQL` stores all structured data: tenant information, user accounts, progress items, analysis results, sources, user-followed terms, content flags, LLM configurations, and custom parser code. Data is isolated by `tenant_id`.
*   **Vector Database:** `ChromaDB` stores vector embeddings of the AI-generated summaries to power semantic search.
*   **AI Model Integration:** Dynamically integrates with `Google Gemini`, `OpenAI`, and other LLM providers based on tenant configurations.

---

## 🚀 Getting Started

Follow these steps to get the entire application stack running locally.

### Prerequisites

*   **Docker & Docker Compose:** Ensure you have the latest versions installed and running on your system.
*   **Git:** For cloning the repository.
*   **Python 3.10+:** For running local setup scripts.
*   **API Keys:** You must have an API key for the **Google Gemini API** (for default/shared LLM usage). You will also need API keys for any other LLM providers (e.g., OpenAI) that your tenants wish to configure. An optional **SendGrid API** key can be used for email digests.

### 1. Clone the Repository

```bash
git clone https://github.com/EricAlex/AI_sentinel.git
cd AI_sentinel
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory by copying the example file:

```bash
cp .env.example .env
```

Now, edit the `.env` file and fill in your actual API keys and secrets. **Ensure `SECRET_KEY` and `ENCRYPTION_KEY` are strong, randomly generated strings.**

```.env
# .env
# --- API SECRETS ---
GOOGLE_API_KEY="YOUR_GEMINI_API_KEY_HERE"
SENDGRID_API_KEY="YOUR_SENDGRID_API_KEY_HERE" # Optional

# --- NEW: Secret key for JWT authentication ---
SECRET_KEY="your_super_secret_jwt_key_here"

# --- NEW: Encryption key for sensitive data (e.g., LLM API keys) ---
ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

# --- INFRASTRUCTURE (Do not change for local deployment) ---
DATABASE_URL="postgresql://user:password@postgres:5432/ai_progress"
CELERY_BROKER_URL="redis://redis:6379/0"
CELERY_RESULT_BACKEND="redis://redis:6379/0"
CHROMA_HOST="chroma"
CHROMA_PORT="8000"

# --- Variables for Django Celery Beat ---
DJANGO_SECRET_KEY="generate-a-random-secret-key-here"
DB_HOST_FOR_DJANGO="postgres"

# --- FastAPI URL for Streamlit to connect to ---
FASTAPI_URL="http://localhost:8001" # Or the appropriate host/port if not running locally
```

### 3. One-Time Database Setup

This process initializes the database and creates all necessary tables for the application.

1.  **Start the PostgreSQL service:**
    ```bash
    docker-compose up -d postgres
    ```
    Wait about 20-30 seconds for the database to initialize and become healthy.

2.  **Create all application tables:** This creates tables like `tenants`, `users`, `progress_items`, `sources`, etc.
    ```bash
    docker-compose run --rm fastapi_app python -c "from database import create_all_tables; create_all_tables()"
    ```

3.  **Run the Django migrations:** This creates the tables required by the `django-celery-beat` scheduler.
    ```bash
    docker-compose run --rm celery_beat sh -c "DJANGO_SETTINGS_MODULE=django_settings python -m django migrate django_celery_beat"
    ```

### 4. Launch the Application

Now, build the images and launch the full application stack.

```bash
docker-compose up --build -d
```

### 5. Access the Services

*   **Main Web UI:** Open your browser and go to `http://localhost:8501`
*   **FastAPI Backend (API Docs):** Access the API documentation at `http://localhost:8001/docs`

### 6. Initial User Setup

When you first access the Streamlit UI, you will be prompted to log in or register.

*   **Register a new tenant and user:** Provide a username, password, and a tenant name. This user will be a **regular tenant user** and will NOT have administrative privileges by default.

### 7. Creating a System Administrator

Regular tenant users cannot register as administrators. To create a system-level administrator (who can manage shared sources and other global settings), you must use a separate CLI command:

1.  **Ensure all Docker containers are running.**
2.  **Execute the system admin creation script:**
    ```bash
    docker-compose exec fastapi_app python create_system_admin.py <username> <password>
    ```
    Replace `<username>` and `<password>` with the desired credentials for your system administrator.

    **Example:**
    ```bash
    docker-compose exec fastapi_app python create_system_admin.py admin@example.com supersecretpassword
    ```
    This user will be associated with the `system_shared_sources` tenant and will have `is_admin=True`.

### 8. Using the Admin Dashboard

Log in to the Streamlit UI with a user account that has `is_admin=True` (either a tenant admin you created or the system admin). Navigate to the "Admin Dashboard" page from the UI's sidebar.

*   **LLM Configuration:** Tenant administrators can configure their tenant's LLM settings here.
*   **Source Management:** Tenant administrators can add/edit/delete sources specific to their tenant. System administrators can manage shared sources.

The system is now live! The scraper will run on its schedule (or you can trigger it manually) and start populating the database.

---

## 🛠️ Usage & Management

### Manually Triggering a Scraper Cycle

To trigger a scraper cycle for a specific tenant (e.g., for testing or immediate data refresh):

1.  **Log in to the Streamlit UI** with a tenant administrator account.
2.  Navigate to the **Admin Dashboard**.
3.  Use the "Run Scraper Cycle" button. This will trigger a Celery task that runs the scraper for your tenant's configured sources.

### Monitoring & Debugging

The most important tool for debugging is viewing the logs from the containers.

*   **View all logs (interleaved):**
    ```bash
    docker-compose logs -f
    ```

*   **View logs for a specific service (e.g., the worker):**
    ```bash
    docker-compose logs -f celery_worker
    ```

### Stopping the Application

To stop all running services:
```bash
docker-compose down
```
To stop and remove the database volumes (for a complete reset):
```bash
docker-compose down -v
```

### Parser Maintenance

Web scrapers are brittle and require maintenance as websites change their layouts. The system now supports dynamic, AI-healed parsers.

*   If a source starts failing (as seen in the logs), the AI healing process will attempt to generate a new parser and store it in the database for that specific tenant/source.
*   System administrators can review `ParserProposal` entries in the Admin Dashboard.
*   Manual intervention in `parsers.py` is generally no longer required for individual source fixes, as custom parsers are stored in the database.

---

## 🤝 Contributing

Contributions are welcome! Whether it's adding a new parser, improving the UI, or enhancing the AI prompts, feel free to open an issue to discuss your ideas or submit a pull request.

---

## 📜 License

This project is licensed under the MIT License. See the `LICENSE` file for details.