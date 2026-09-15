"""Lista de feeds oficiais + agregadores. Só edite URLs aqui.

Verificado ao vivo em 2026-09-15 (todos com itens de 0-5 dias).
Anthropic e Groq NÃO têm RSS oficial (404) — são cobertos via HN/TC/Reddit.
"""

FEEDS = [
    {
        "name": "openai-news",
        "company": "openai",
        "official": True,
        "url": "https://openai.com/news/rss.xml",
    },
    {
        "name": "hf-blog",
        "company": "huggingface",
        "official": True,
        "url": "https://huggingface.co/blog/feed.xml",
    },
    {
        "name": "google-ai-blog",
        "company": "google",
        "official": True,
        "url": "https://blog.google/technology/ai/rss/",
    },
    {
        "name": "techcrunch-ai",
        "company": "techcrunch",
        "official": False,
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "name": "hn-front",
        "company": "ycombinator",
        "official": False,
        "url": "https://news.ycombinator.com/rss",
    },
    {
        "name": "reddit-singularity",
        "company": "reddit",
        "official": False,
        "url": "https://www.reddit.com/r/singularity/new/.rss",
    },
]
