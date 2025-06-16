
# 🧠 The AI Progress Sentinel

**The AI Progress Sentinel is an automated, AI-powered application that discovers, analyzes, and ranks the latest breakthroughs in Artificial Intelligence.**

This system continuously scans a wide range of sources—from academic pre-print servers like arXiv to the official blogs of major AI labs—to ensure you never miss an important development. It uses the Google Gemini Pro model to generate insightful, structured summaries and to score each breakthrough based on its novelty, potential impact, and influence on the field. All this information is presented in a clean, interactive, and searchable web dashboard built with Streamlit.

 
*(Note: You should replace this with a real screenshot of your app)*

---

## ✨ Features

*   **Multi-Source Aggregation:** Continuously scrapes a curated and expandable list of sources, including:
    *   arXiv (cs.AI, cs.LG, cs.CV, etc.)
    *   Official AI Blogs (Microsoft Research, and others as they are maintained)
*   **AI-Powered Summarization & Ranking:** Uses Google Gemini to perform a two-step analysis on each item:
    1.  **Summarization:** Generates a structured summary explaining what's new, how it works, and why it matters.
    2.  **Ranking:** Scores the breakthrough on multiple axes (Novelty, Human Impact, Field Influence, Technical Maturity) with justifications.
*   **Semantic Search:** Powered by vector embeddings, allowing users to search for concepts and ideas, not just keywords (e.g., "alternatives to transformers").
*   **Interactive Dashboard:** A modern web UI built with Streamlit for intuitive filtering, sorting, and exploration of AI progress.
*   **Personalization:** Users can "follow" specific keywords or authors to create a personalized feed.
*   **Automated & Resilient:** Built on a production-grade, containerized architecture using Docker and Celery to handle background processing, task queuing, and automatic retries.
*   **AI-Driven Source Discovery:** A `sourcerer` service that periodically finds and validates new potential AI blogs to add to the ingestion pipeline.
*   **Admin & Health Dashboard:** A password-protected page to monitor system health, service status, and review user-flagged content.

---

## 🏗️ System Architecture

The application is built on a modern, decoupled, multi-service architecture, fully containerized with Docker for easy deployment and scalability.

 
*(Note: You should replace this with a real diagram if you have one)*

*   **Frontend (UI):** `Streamlit` provides the interactive user dashboard.
*   **Backend (Workers):** `Celery` manages a distributed task queue for all heavy processing, ensuring the UI remains fast and responsive.
*   **Message Broker:** `Redis` handles the task queue, mediating between the scraper/scheduler and the Celery workers.
*   **Scheduler:** `Celery Beat` with the `django-celery-beat` backend triggers recurring tasks like scraping and reporting.
*   **Relational Database:** `PostgreSQL` stores all structured data: progress items, analysis results, sources, user-followed terms, and content flags.
*   **Vector Database:** `ChromaDB` stores vector embeddings of the AI-generated summaries to power semantic search.
*   **AI Model:** `Google Gemini Pro` (or Flash) is used via its API for all summarization and ranking tasks.

---

## 🚀 Getting Started

Follow these steps to get the entire application stack running locally.

### Prerequisites

*   **Docker & Docker Compose:** Ensure you have the latest versions installed and running on your system.
*   **Git:** For cloning the repository.
*   **Python 3.10+:** For running local setup scripts.
*   **API Keys:** You must have an API key for the **Google Gemini API**. An optional **SendGrid API** key can be used for email digests.

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/ai-progress-sentinel.git
cd ai-progress-sentinel
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory by copying the example file:

```bash
cp .env.example .env
```

Now, edit the `.env` file and fill in your actual API keys and secrets:

```.env
# .env
# --- API SECRETS ---
GOOGLE_API_KEY="YOUR_GEMINI_API_KEY_HERE"
SENDGRID_API_KEY="YOUR_SENDGRID_API_KEY_HERE" # Optional
ADMIN_PASSWORD="a_strong_password_for_the_dashboard"

# --- DJANGO CELERY BEAT ---
DJANGO_SECRET_KEY="generate-a-random-secret-key-here"
DB_HOST_FOR_DJANGO="postgres"

# --- INFRASTRUCTURE (Do not change for local deployment) ---
DATABASE_URL="postgresql://user:password@postgres:5432/ai_progress"
CELERY_BROKER_URL="redis://redis:6379/0"
CELERY_RESULT_BACKEND="redis://redis:6379/0"
CHROMA_HOST="chroma"
CHROMA_PORT="8000"
```

### 3. One-Time Database Setup

This process initializes the database, creates all necessary tables for the application, and sets up the scheduler's tables.

1.  **Start the PostgreSQL service:**
    ```bash
    docker-compose up -d postgres
    ```
    Wait about 20-30 seconds for the database to initialize.

2.  **Run the application setup script:** This creates our app's tables (`progress_items`, `sources`, etc.) and populates the initial sources.
    ```bash
    docker-compose run --rm celery_worker python initial_setup.py
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
*   **Admin Dashboard:** Navigate to the "Admin Dashboard" page from the UI's sidebar and use the password you set in `.env`.

The system is now live! The scraper will run on its schedule (or you can trigger it manually) and start populating the database.

---

## 🛠️ Usage & Management

### Manually Triggering a Scrape

To test the full pipeline immediately without waiting for the scheduler:
```bash
docker-compose exec celery_worker python -c "from tasks import run_scraper_cycle; run_scraper_cycle.delay()"
```

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

Web scrapers are brittle and require maintenance as websites change their layouts. The `parsers.py` file contains the logic for each source. If a source starts failing (as seen in the logs), follow the **Parser Maintenance Workflow**:

1.  Use `manage_sources.py` to disable the broken source to maintain system stability.
2.  In a browser, visit the source's URL and use "Inspect Element" to find the new HTML selectors for articles.
3.  Update the corresponding function in `parsers.py` with the new selectors.
4.  Re-enable the source using `manage_sources.py`.
5.  Rebuild and restart the stack to apply the changes (`docker-compose up --build -d`).

---

## 🤝 Contributing

Contributions are welcome! Whether it's adding a new parser, improving the UI, or enhancing the AI prompts, feel free to open an issue to discuss your ideas or submit a pull request.

---

## 📜 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
