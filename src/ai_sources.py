"""
AI-focused news sources for the AI-creator-profile scraper.
Curated to match the kinds of stories the AI creator covers in his 17 reels:
model launches, dev tools, repos, benchmarks, agent products.

No politics, no India-trending, no general tech feeds.
"""

AI_RSS_FEEDS = [
    # ─── AI-focused news outlets ───
    {"name": "TechCrunch AI",    "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "ai_news"},
    {"name": "The Decoder",      "url": "https://the-decoder.com/feed/",                                  "category": "ai_news"},
    {"name": "VentureBeat AI",   "url": "https://venturebeat.com/category/ai/feed/",                     "category": "ai_news"},
    {"name": "MIT Tech Review",  "url": "https://www.technologyreview.com/feed/",                        "category": "ai_news"},
    {"name": "Ars AI",           "url": "https://feeds.arstechnica.com/arstechnica/index",               "category": "ai_news"},

    # ─── AI lab blogs (highest signal — direct from source) ───
    {"name": "Anthropic Blog",   "url": "https://www.anthropic.com/news/rss.xml",                        "category": "ai_lab"},
    {"name": "OpenAI Blog",      "url": "https://openai.com/blog/rss.xml",                               "category": "ai_lab"},
    {"name": "Google Research",  "url": "https://research.google/blog/rss/",                             "category": "ai_lab"},
    {"name": "DeepMind Blog",    "url": "https://deepmind.google/blog/rss.xml",                          "category": "ai_lab"},
    {"name": "HuggingFace Blog", "url": "https://huggingface.co/blog/feed.xml",                          "category": "ai_lab"},

    # ─── Indian AI coverage (when it's product/tool focused) ───
    {"name": "AnalyticsIndiaMag","url": "https://analyticsindiamag.com/feed/",                           "category": "ai_news"},
    {"name": "Inc42 AI",         "url": "https://inc42.com/category/artificial-intelligence/feed/",      "category": "ai_news"},

    # ─── Repo / model release feeds ───
    {"name": "GitHub Trending Py", "url": "https://github.com/trending/python.atom?since=daily",         "category": "ai_repo"},
    {"name": "HF Daily Papers",  "url": "https://huggingface.co/papers/feed",                            "category": "ai_research"},

    # ─── Aggregators that surface AI stories ───
    {"name": "HN AI Search",     "url": "https://hnrss.org/newest?q=AI+OR+LLM+OR+Claude+OR+Anthropic&count=30", "category": "ai_news"},
]

# Hacker News stories tagged 'ai' or showing 'show HN' for new tools
HN_AI_API = "https://hn.algolia.com/api/v1/search?tags=story&query=AI&hitsPerPage=30"