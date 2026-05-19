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

    # Platform / policy / leaks (global)
    {"name": "9to5Mac",          "url": "https://9to5mac.com/feed/",                          "category": "platform"},
    {"name": "9to5Google",       "url": "https://9to5google.com/feed/",                       "category": "platform"},

    # ─── INDIAN tech / business news ───
    {"name": "Inc42",            "url": "https://inc42.com/feed/",                            "category": "india_tech"},
    {"name": "YourStory",        "url": "https://yourstory.com/feed",                         "category": "india_tech"},
    {"name": "MoneyControl Tech","url": "https://www.moneycontrol.com/rss/technology.xml",    "category": "india_tech"},
    {"name": "The Ken (free)",   "url": "https://the-ken.com/feed/",                          "category": "india_tech"},
    {"name": "ET Tech",          "url": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", "category": "india_tech"},

    # ─── INDIAN tech POLICY & GOVERNMENT — for senior's feed ───
    # These cover MeitY, TRAI, RBI, SEBI, DPDP Act, AI regulation, fintech rules, data protection.
    {"name": "Medianama",        "url": "https://www.medianama.com/feed/",                    "category": "india_tech_policy"},
    {"name": "MediaNama Reg",    "url": "https://www.medianama.com/category/regulation/feed/", "category": "india_tech_policy"},
    {"name": "ET Telecom",       "url": "https://telecom.economictimes.indiatimes.com/rss/topstories", "category": "india_tech_policy"},
    {"name": "BW Legal World",   "url": "https://bwlegalworld.com/rss/category/technology",   "category": "india_tech_policy"},
    {"name": "Internet Freedom", "url": "https://internetfreedom.in/rss/",                    "category": "india_tech_policy"},
    {"name": "ET Fintech",       "url": "https://bfsi.economictimes.indiatimes.com/rss/fintech", "category": "india_tech_policy"},

    # ─── AI policy specifically (India-relevant where possible) ───
    {"name": "AnalyticsIndiaMag","url": "https://analyticsindiamag.com/feed/",                "category": "india_ai_policy"},

    # ─── INDIAN trending news — primary content category for Prakhar ───
    # Mix of: tech-focused trending (Wire Tech, NDTV Gadgets) for Mythos/AI stories
    # AND general Indian news (Print, Wire, Scroll) for Modi/Chadha/China-rule type stories.
    # The scorer's viral-keyword boost filters for ones with public figures, geopolitics,
    # or controversy markers; pure entertainment gets downweighted.
    {"name": "The Print",        "url": "https://theprint.in/feed/",                          "category": "india_trending"},
    {"name": "The Wire",         "url": "https://thewire.in/rss",                             "category": "india_trending"},
    {"name": "Scroll.in",        "url": "https://scroll.in/feeds/all.rss",                    "category": "india_trending"},
    {"name": "NDTV Gadgets",     "url": "https://feeds.feedburner.com/gadgets360-latest",     "category": "india_trending"},
    {"name": "HT Tech",          "url": "https://tech.hindustantimes.com/rss/feeds/news",     "category": "india_trending"},
    {"name": "ThePrint Tech",    "url": "https://theprint.in/category/tech/feed/",            "category": "india_trending"},
    {"name": "Business Std Tech","url": "https://www.business-standard.com/rss/technology-108.rss", "category": "india_trending"},
    {"name": "Times India Tech", "url": "https://timesofindia.indiatimes.com/rssfeeds/66949542.cms", "category": "india_trending"},

    # ─── AI startups & funding (Indian + global) ───
    # (Tracxn dropped — RSS feed returns archive data instead of recent items.)
]

# Hacker News & Reddit are pulled via JSON APIs in fetcher.py
HN_TOP_STORIES = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"

REDDIT_FEEDS = [
    {"name": "r/technology",     "url": "https://www.reddit.com/r/technology/top.json?t=day&limit=25"},
    {"name": "r/artificial",     "url": "https://www.reddit.com/r/artificial/top.json?t=day&limit=25"},
    {"name": "r/MachineLearning","url": "https://www.reddit.com/r/MachineLearning/top.json?t=day&limit=15"},
]