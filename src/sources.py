"""
News sources configuration.
Add/remove feeds here. Categories help with diversity scoring later.
"""

RSS_FEEDS = [
    # Big Tech & general
    {"name": "TechCrunch",       "url": "https://techcrunch.com/feed/",                       "category": "bigtech"},
    {"name": "The Verge",        "url": "https://www.theverge.com/rss/index.xml",             "category": "bigtech"},
    {"name": "Ars Technica",     "url": "https://feeds.arstechnica.com/arstechnica/index",    "category": "deep_tech"},
    {"name": "Engadget",         "url": "https://www.engadget.com/rss.xml",                   "category": "bigtech"},
    {"name": "Wired",            "url": "https://www.wired.com/feed/rss",                     "category": "deep_tech"},
    {"name": "MIT Tech Review",  "url": "https://www.technologyreview.com/feed/",             "category": "ai_research"},

    # AI / ML focused
    {"name": "VentureBeat AI",   "url": "https://venturebeat.com/category/ai/feed/",          "category": "ai_research"},
    {"name": "The Decoder",      "url": "https://the-decoder.com/feed/",                      "category": "ai_research"},

    # Platform / policy / leaks
    {"name": "9to5Mac",          "url": "https://9to5mac.com/feed/",                          "category": "platform"},
    {"name": "9to5Google",       "url": "https://9to5google.com/feed/",                       "category": "platform"},

    # ─── INDIAN sources — high weight for EZ Snippet-style content ───
    # These surface the Zomato-commission, UPI-rule, RBI-mandate type stories.
    {"name": "Inc42",            "url": "https://inc42.com/feed/",                            "category": "india_tech"},
    {"name": "YourStory",        "url": "https://yourstory.com/feed",                         "category": "india_tech"},
    {"name": "Entrackr",         "url": "https://entrackr.com/feed/",                         "category": "india_tech"},
    {"name": "MoneyControl Tech","url": "https://www.moneycontrol.com/rss/technology.xml",    "category": "india_tech"},
    {"name": "The Ken (free)",   "url": "https://the-ken.com/feed/",                          "category": "india_tech"},
    {"name": "ET Tech",          "url": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", "category": "india_tech"},
    {"name": "Medianama",        "url": "https://www.medianama.com/feed/",                    "category": "india_policy"},
]

# Hacker News & Reddit are pulled via JSON APIs in fetcher.py
HN_TOP_STORIES = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"

REDDIT_FEEDS = [
    {"name": "r/technology",     "url": "https://www.reddit.com/r/technology/top.json?t=day&limit=25"},
    {"name": "r/artificial",     "url": "https://www.reddit.com/r/artificial/top.json?t=day&limit=25"},
    {"name": "r/MachineLearning","url": "https://www.reddit.com/r/MachineLearning/top.json?t=day&limit=15"},
]