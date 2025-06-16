# parsers.py

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import re
from urllib.parse import urljoin

# --- Standard Request Headers to mimic a browser ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Connection': 'keep-alive',
}

# --- Helper Function for Making Requests ---
def get_soup(url):
    """Fetches a URL and returns a BeautifulSoup object, or None on failure."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()  # Will raise an HTTPError for bad responses (4xx or 5xx)
        return BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException as e:
        print(f"PARSER: Request failed for {url}: {e}")
        return None

# --- Individual Parsers ---
# NOTE: These selectors are based on website structures as of mid-2024.
# They are the most brittle part of the application and will require periodic maintenance.

def parse_google_blog(url: str, source_name: str, max_results=8):
    """Parses blogs using Google's common 'card' layout (Google AI, DeepMind)."""
    soup = get_soup(url)
    if not soup: return []
    
    articles = soup.find_all('a', class_='card', limit=max_results)
    posts = []
    for article in articles:
        try:
            post_url = urljoin(url, article['href'])
            title = article.find('h3').text.strip()
            abstract = article.find('p').text.strip()
            date_str = article.find('p', class_='date').text
            published_date = datetime.strptime(date_str, '%B %d, %Y')
            
            posts.append({
                "entry_id": post_url, "title": title, "abstract": abstract,
                "authors": [source_name], "published_date": published_date,
                "url": post_url, "source": source_name
            })
        except Exception as e:
            print(f"PARSER: Failed to parse a card from {source_name}: {e}")
            continue
    return posts

def parse_openai_blog(url: str, source_name: str, max_results=8):
    """Parses the OpenAI Blog."""
    soup = get_soup(url)
    if not soup: return []

    articles = soup.find_all('a', href=lambda href: href and href.startswith('/blog/'))
    posts = []
    unique_urls = set()
    for article in articles:
        if len(posts) >= max_results: break
        
        post_url = urljoin(url, article['href'])
        if post_url in unique_urls: continue

        title_tag = article.find(['h2', 'h3', 'div'], attrs={'data-testid': re.compile(r'heading')})
        if not title_tag: continue
        
        title = title_tag.text.strip()
        abstract = f"A new post titled '{title}' from the OpenAI blog. Full content will be analyzed."

        posts.append({
            "entry_id": post_url, "title": title, "abstract": abstract,
            "authors": ["OpenAI"], "published_date": datetime.utcnow(),
            "url": post_url, "source": source_name
        })
        unique_urls.add(post_url)
    return posts

def parse_meta_blog(url: str, source_name: str, max_results=8):
    """Parses the Meta AI Blog, which uses a more modern card structure."""
    soup = get_soup(url)
    if not soup: return []

    # Meta uses a parent div with a role of 'article' for each post card
    articles = soup.find_all('div', role='article', limit=max_results)
    posts = []
    for article in articles:
        try:
            link_tag = article.find('a', href=True)
            if not link_tag: continue
            
            post_url = urljoin(url, link_tag['href'])
            title = link_tag.text.strip()
            # The abstract is often in a sibling or child element, this is a bit fragile
            abstract_tag = article.find('div', class_=lambda c: c and 'description' in c)
            abstract = abstract_tag.text.strip() if abstract_tag else f"A new post titled '{title}' from Meta AI."

            posts.append({
                "entry_id": post_url, "title": title, "abstract": abstract,
                "authors": ["Meta AI"], "published_date": datetime.utcnow(),
                "url": post_url, "source": source_name
            })
        except Exception as e:
            print(f"PARSER: Failed to parse a card from {source_name}: {e}")
            continue
    return posts

def parse_huggingface_blog(url: str, source_name: str, max_results=8):
    """Parses the Hugging Face Blog."""
    soup = get_soup(url)
    if not soup: return []
    
    articles = soup.find_all('a', class_='block', limit=max_results*2)
    posts = []
    for article in articles:
        if '/blog/' not in article['href']: continue
        if len(posts) >= max_results: break

        try:
            post_url = urljoin(url, article['href'])
            title = article.find('h3').text.strip()
            abstract = article.find('div', class_='text-gray-500').text.strip()
            
            posts.append({
                "entry_id": post_url, "title": title, "abstract": abstract,
                "authors": ["Hugging Face"], "published_date": datetime.utcnow(),
                "url": post_url, "source": source_name
            })
        except Exception as e:
            print(f"PARSER: Failed to parse a card from {source_name}: {e}")
            continue
    return posts

def parse_microsoft_blog(url: str, source_name: str, max_results=8):
    """Parses the Microsoft Research AI Blog."""
    soup = get_soup(url)
    if not soup: return []

    articles = soup.find_all('article', limit=max_results)
    posts = []
    for article in articles:
        try:
            link_tag = article.find('a', href=True)
            post_url = link_tag['href']
            title = article.find(['h3', 'h2']).text.strip()
            abstract_tag = article.find('p')
            abstract = abstract_tag.text.strip() if abstract_tag else ""
            time_tag = article.find('time')
            published_date = datetime.fromisoformat(time_tag['datetime'].replace('Z', '+00:00')) if time_tag else datetime.utcnow()

            posts.append({
                "entry_id": post_url, "title": title, "abstract": abstract,
                "authors": ["Microsoft Research"], "published_date": published_date,
                "url": post_url, "source": source_name
            })
        except Exception as e:
            print(f"PARSER: Failed to parse a card from {source_name}: {e}")
            continue
    return posts

def parse_techreview_ai(url: str, source_name: str, max_results=8):
    """Parses the MIT Technology Review AI section."""
    soup = get_soup(url)
    if not soup: return []

    articles = soup.find_all('div', class_=re.compile(r'promo-container'), limit=max_results)
    posts = []
    for article in articles:
        try:
            link_tag = article.find('a', href=True)
            if not link_tag: continue
            
            post_url = urljoin(url, link_tag['href'])
            title_tag = article.find(['h2', 'h3'])
            title = title_tag.text.strip() if title_tag else "Untitled"
            
            abstract_tag = article.find('p')
            abstract = abstract_tag.text.strip() if abstract_tag else ""
            
            posts.append({
                "entry_id": post_url, "title": title, "abstract": abstract,
                "authors": ["MIT Tech Review"], "published_date": datetime.utcnow(),
                "url": post_url, "source": source_name
            })
        except Exception as e:
            print(f"PARSER: Failed to parse a card from {source_name}: {e}")
            continue
    return posts

def parse_gradient_pub(url: str, source_name: str, max_results=8):
    """Parses The Gradient publication."""
    soup = get_soup(url)
    if not soup: return []

    articles = soup.find_all('div', class_='post-card', limit=max_results)
    posts = []
    for article in articles:
        try:
            link_tag = article.find('a', class_='post-card-image-link', href=True)
            if not link_tag: continue
            
            post_url = urljoin(url, link_tag['href'])
            title_tag = article.find('h2', class_='post-card-title')
            title = title_tag.text.strip() if title_tag else "Untitled"
            
            abstract_tag = article.find('div', class_='post-card-excerpt')
            abstract = abstract_tag.text.strip() if abstract_tag else ""
            
            posts.append({
                "entry_id": post_url, "title": title, "abstract": abstract,
                "authors": ["The Gradient"], "published_date": datetime.utcnow(),
                "url": post_url, "source": source_name
            })
        except Exception as e:
            print(f"PARSER: Failed to parse a card from {source_name}: {e}")
            continue
    return posts

def parse_nvidia_blog(url: str, source_name: str, max_results=8):
    """Parses the NVIDIA AI Blog."""
    soup = get_soup(url)
    if not soup: return []

    articles = soup.find_all('li', class_='item', limit=max_results)
    posts = []
    for article in articles:
        try:
            link_tag = article.find('a', href=True)
            if not link_tag: continue
            
            post_url = link_tag['href'] # NVIDIA uses full URLs
            title = article.find('h3').text.strip()
            
            abstract_tag = article.find('p')
            abstract = abstract_tag.text.strip() if abstract_tag else ""
            
            posts.append({
                "entry_id": post_url, "title": title, "abstract": abstract,
                "authors": ["NVIDIA"], "published_date": datetime.utcnow(),
                "url": post_url, "source": source_name
            })
        except Exception as e:
            print(f"PARSER: Failed to parse a card from {source_name}: {e}")
            continue
    return posts

# --- Parser Dispatcher Dictionary ---
# This dictionary maps the `source_type` from the database to the correct parser function.
# This makes the system pluggable and easy to extend. To add a new source, you
# create a `parse_new_source` function and add its mapping here.
PARSER_MAP = {
    'google_blog': parse_google_blog,
    'deepmind_blog': parse_google_blog, # DeepMind uses the same layout as Google AI
    'openai_blog': parse_openai_blog,
    'meta_blog': parse_meta_blog,
    'huggingface_blog': parse_huggingface_blog,
    'nvidia_blog': parse_nvidia_blog,
    'microsoft_blog': parse_microsoft_blog,
    'techreview_ai': parse_techreview_ai,
    'gradient_pub': parse_gradient_pub,
}