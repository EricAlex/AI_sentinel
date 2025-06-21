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

def parse_google_blog(url: str, source_name: str, max_results=8) -> list:

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    results = []
    
    # The main repeating container for each article is a list item within a specific UL
    articles = soup.select('ul.gdm-pagination__list li.glue-grid__col')

    for article in articles[:max_results]:
        try:
            card = article.find('a', class_='glue-card')
            if not card:
                continue

            # 1. Get the full URL to the article
            post_url = card.get('href')
            if not post_url:
                continue
            
            # Ensure the URL is absolute
            post_url = urljoin(url, post_url)

            # 2. Get the entry_id from the URL slug
            entry_id = post_url.strip('/').split('/')[-1]

            # 3. Get the title of the article
            title_tag = card.find('p', class_='glue-headline--headline-5')
            title = title_tag.get_text(strip=True) if title_tag else 'No title available'

            # 4. Get the abstract or summary
            abstract_tag = card.find('p', class_='glue-card__description')
            abstract = abstract_tag.get_text(strip=True) if abstract_tag else ''

            # 5. Get the published date
            date_tag = card.find('time')
            published_date_str = date_tag['datetime'] if date_tag and date_tag.has_attr('datetime') else None
            
            if published_date_str:
                # Parse date and format to ISO 8601 with UTC timezone
                dt_obj = datetime.strptime(published_date_str, '%Y-%m-%d')
                published_date = dt_obj.strftime('%Y-%m-%dT00:00:00Z')
            else:
                published_date = None
            
            # 6. Get authors (not available on the list page)
            authors = []

            results.append({
                "entry_id": entry_id,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "published_date": published_date,
                "url": post_url,
                "source": source_name,
            })

        except Exception as e:
            print(f"Skipping a post due to parsing error: {e}")
            continue
            
    return results

def parse_openai_blog(url: str, source_name: str, max_results=8) -> list:

    # Enhanced headers to mimic a real browser and avoid 403 Forbidden errors.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    results = []
    
    # Articles are within 'li' tags, which contain an 'a' tag.
    posts = soup.select('#content ul > li a[href]')

    for post in posts[:max_results]:
        try:
            # 1. Get the full URL to the article
            href = post.get('href')
            if not href or not href.startswith('/research/'):
                continue
            
            post_url = urljoin(response.url, href)

            # 2. Use the URL slug as a unique entry_id
            entry_id = href.strip('/').split('/')[-1]

            # 3. Get the title of the article
            title_tag = post.find('h3')
            title = title_tag.get_text(strip=True) if title_tag else 'No title available'
            
            # 4. Get the abstract or summary
            abstract_tag = post.find('p')
            abstract = abstract_tag.get_text(strip=True) if abstract_tag else ''

            # 5. Get the published date from the 'data-date' attribute for reliability
            date_tag = post.find('span', attrs={'data-date': True})
            published_date = None
            if date_tag and date_tag.has_attr('data-date'):
                published_date_str = date_tag['data-date']
                try:
                    dt_obj = datetime.strptime(published_date_str, '%Y-%m-%d')
                    published_date = dt_obj.strftime('%Y-%m-%dT00:00:00Z')
                except ValueError as ve:
                    print(f"Date format error for {published_date_str}: {ve}")

            # 6. Authors are not listed on the main blog page
            authors = []

            results.append({
                "entry_id": entry_id,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "published_date": published_date,
                "url": post_url,
                "source": source_name,
            })

        except Exception as e:
            print(f"Skipping a post due to a parsing error: {e}")
            continue

    return results

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

def parse_huggingface_blog(url: str, source_name: str, max_results=8) -> list:

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    results = []
    
    # Articles are contained within divs with a 'data-target' attribute.
    # The data is conveniently stored in a 'data-props' JSON string.
    article_divs = soup.select('div[data-target="BlogThumbnail"]')

    for article_div in article_divs[:max_results]:
        try:
            props_str = article_div.get('data-props')
            if not props_str:
                continue

            data = json.loads(props_str)
            blog_data = data.get('blog')

            if not blog_data:
                continue
            
            slug = blog_data.get('slug')
            if not slug:
                continue
                
            post_url = urljoin(url, f"blog/{slug}")
            entry_id = slug

            title = blog_data.get('title', 'No title available')
            
            authors_list = blog_data.get('authors', [])
            authors = [author.get('user') for author in authors_list if author.get('user')]
            
            published_date_str = blog_data.get('publishedAt')
            
            # Ensure the date is valid and format it consistently
            if published_date_str:
                # The date is already in ISO 8601 format, e.g., "2025-06-16T00:00:00.000Z"
                # We can parse it to validate and then reformat, or use as is.
                # Let's parse and reformat to ensure consistency without milliseconds.
                dt_obj = datetime.strptime(published_date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                published_date = dt_obj.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                published_date = None
            
            results.append({
                "entry_id": entry_id,
                "title": title,
                "abstract": "",  # No abstract available on the blog listing page
                "authors": authors,
                "published_date": published_date,
                "url": post_url,
                "source": source_name,
            })

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            print(f"Skipping a post due to parsing error: {e}")
            continue
            
    return results

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