"""Seed content definitions (placeholders — flagged needs_verification)."""
from __future__ import annotations

# NOTE: All real-world facts about "Georgie" (surname, phone, prices, licences)
# are intentional placeholders. Do NOT treat these as confirmed offerings.


def L(en: str, ka: str | None = None, ar: str | None = None) -> dict:
    d = {"en": en}
    if ka:
        d["ka"] = ka
    if ar:
        d["ar"] = ar
    return d


# --- 10 seed tours ----------------------------------------------------------
# Each: realistic editable copy. priceDisplay="contact", needs_verification.
TOURS = [
    {
        "slug": "ushguli-shkhara-private-day-journey",
        "name": L("Ushguli and Shkhara Private Day Journey",
                  "უშგული და შხარა — კერძო დღიური მოგზაურობა",
                  "رحلة يوم خاصة إلى أوشغولي وشخارا"),
        "shortDescription": L(
            "A full-day private drive from Mestia to Ushguli, one of Europe's "
            "highest continuously inhabited villages, with time beneath the "
            "Shkhara massif.",
            "სრული დღის კერძო მოგზაურობა მესტიიდან უშგულამდე.",
            "جولة خاصة ليوم كامل من مستيا إلى قرية أوشغولي."),
        "difficulty": "easy", "tourType": "private", "durationDays": 1,
        "durationHours": 9, "seasons": ["summer", "autumn"],
        "familyFriendly": True, "lowWalking": True, "winter": False,
        "featured": True, "displayOrder": 1,
        "categories": ["culture", "scenery", "villages"],
        "publish": True,
    },
    {
        "slug": "koruldi-lakes-4x4-short-walk",
        "name": L("Koruldi Lakes 4×4 and Short Walk"),
        "shortDescription": L(
            "A 4×4 climb above Mestia toward the Koruldi Lakes with a short "
            "final walk to the ridgeline viewpoints over the Caucasus."),
        "difficulty": "moderate", "tourType": "private", "durationDays": 1,
        "durationHours": 6, "seasons": ["summer"], "familyFriendly": True,
        "lowWalking": True, "winter": False, "featured": True, "displayOrder": 2,
        "categories": ["scenery", "4x4", "hiking"], "publish": True,
    },
    {
        "slug": "koruldi-lakes-sunrise-experience",
        "name": L("Koruldi Lakes Sunrise Experience"),
        "shortDescription": L(
            "An early departure to reach the Koruldi Lakes for sunrise light "
            "on the peaks, returning to Mestia for a late breakfast."),
        "difficulty": "moderate", "tourType": "private", "durationDays": 1,
        "durationHours": 5, "seasons": ["summer"], "familyFriendly": False,
        "lowWalking": False, "winter": False, "featured": False, "displayOrder": 3,
        "categories": ["scenery", "photography"], "publish": True,
    },
    {
        "slug": "chalaadi-glacier-guided-walk",
        "name": L("Chalaadi Glacier Guided Walk",
                  "ჩალაადის მყინვარის ლაშქრობა"),
        "shortDescription": L(
            "A guided walk through birch forest to the tongue of the Chalaadi "
            "Glacier, a gentle introduction to Svaneti's high country.",
            "გიდით ლაშქრობა ჩალაადის მყინვარამდე."),
        "difficulty": "easy", "tourType": "shared", "durationDays": 1,
        "durationHours": 5, "seasons": ["summer", "autumn"], "familyFriendly": True,
        "lowWalking": True, "winter": False, "featured": True, "displayOrder": 4,
        "categories": ["hiking", "glacier", "nature"], "publish": True,
    },
    {
        "slug": "mazeri-shdugra-waterfall",
        "name": L("Mazeri and Shdugra Waterfall"),
        "shortDescription": L(
            "A day in the Mazeri valley beneath Ushba, walking to the Shdugra "
            "Waterfall through meadows and forest."),
        "difficulty": "moderate", "tourType": "shared", "durationDays": 1,
        "durationHours": 7, "seasons": ["summer"], "familyFriendly": True,
        "lowWalking": False, "winter": False, "featured": False, "displayOrder": 5,
        "categories": ["hiking", "waterfall", "scenery"], "publish": True,
    },
    {
        "slug": "mestia-culture-towers-local-food",
        "name": L("Mestia Culture, Towers and Local Food",
                  "მესტიის კულტურა, კოშკები და ადგილობრივი სამზარეულო",
                  "ثقافة مستيا وأبراجها والمأكولات المحلية"),
        "shortDescription": L(
            "A walking day in Mestia: Svan tower houses, the local museum, and "
            "an introduction to Svan cuisine.",
            "ფეხით გასეირნება მესტიაში.",
            "يوم مشي في مستيا يشمل أبراج سفان والمتحف المحلي."),
        "difficulty": "easy", "tourType": "private", "durationDays": 1,
        "durationHours": 4, "seasons": ["spring", "summer", "autumn", "winter"],
        "familyFriendly": True, "lowWalking": True, "winter": True,
        "featured": True, "displayOrder": 6,
        "categories": ["culture", "food", "history"], "publish": True,
    },
    {
        "slug": "hidden-villages-of-svaneti",
        "name": L("Hidden Villages of Svaneti"),
        "shortDescription": L(
            "A flexible day exploring lesser-visited Svan hamlets, their towers "
            "and the families who still live among them."),
        "difficulty": "easy", "tourType": "private", "durationDays": 1,
        "durationHours": 8, "seasons": ["summer", "autumn"], "familyFriendly": True,
        "lowWalking": True, "winter": False, "featured": False, "displayOrder": 7,
        "categories": ["culture", "villages", "offbeat"], "publish": True,
    },
    {
        "slug": "winter-ski-area-transfer-local-support",
        "name": L("Winter Ski-Area Transfer and Local Support"),
        "shortDescription": L(
            "Transfers to the Hatsvali and Tetnuldi ski areas with local "
            "support for equipment, tickets and timing."),
        "difficulty": "easy", "tourType": "private", "durationDays": 1,
        "durationHours": 6, "seasons": ["winter"], "familyFriendly": True,
        "lowWalking": True, "winter": True, "featured": False, "displayOrder": 8,
        "categories": ["winter", "ski", "transfer"], "publish": True,
    },
    {
        "slug": "custom-svaneti-itinerary",
        "name": L("Custom Svaneti Itinerary"),
        "shortDescription": L(
            "Tell us your interests, pace and dates and we will shape a "
            "private multi-day itinerary through Svaneti."),
        "difficulty": "moderate", "tourType": "custom", "durationDays": 3,
        "seasons": ["spring", "summer", "autumn", "winter"], "familyFriendly": True,
        "lowWalking": False, "winter": True, "featured": False, "displayOrder": 9,
        "categories": ["custom", "multiday"],
        "publish": False,  # kept as draft to demonstrate draft/public separation
    },
    {
        "slug": "kutaisi-zugdidi-tbilisi-transfer-to-mestia",
        "name": L("Kutaisi, Zugdidi or Tbilisi Transfer to Mestia"),
        "shortDescription": L(
            "Comfortable road transfers between Mestia and the gateways of "
            "Kutaisi, Zugdidi or Tbilisi, with stops en route."),
        "difficulty": "easy", "tourType": "private", "durationDays": 1,
        "durationHours": 8, "seasons": ["spring", "summer", "autumn", "winter"],
        "familyFriendly": True, "lowWalking": True, "winter": True,
        "featured": False, "displayOrder": 10,
        "categories": ["transfer", "logistics"], "publish": True,
    },
]

# Shared editable defaults applied to every tour
TOUR_DEFAULTS = {
    "fullDescription": L(
        "<p>This is placeholder tour copy for the Svaneti with Georgie CMS. "
        "Replace it with verified details before publishing to production.</p>"),
    "accessibilityNotes": L(
        "Placeholder accessibility notes — confirm terrain, walking surfaces "
        "and vehicle access with the guide."),
    "safetyNotes": L(
        "Placeholder safety notes — weather in the high Caucasus changes "
        "quickly; bring layers and follow the guide's advice."),
    "inclusions": [L("Private guide and driver"), L("Transport in a suitable vehicle"),
                   L("Bottled water")],
    "exclusions": [L("Meals unless stated"), L("Personal expenses"),
                   L("Travel insurance")],
    "whatToBring": [L("Sturdy footwear"), L("Warm layers and rain shell"),
                    L("Sun protection")],
    "itinerary": [
        {"title": L("Departure from Mestia"),
         "body": L("Morning pickup and briefing.")},
        {"title": L("Main experience"),
         "body": L("The core of the day — see the description.")},
        {"title": L("Return"),
         "body": L("Return to Mestia in the afternoon or evening.")},
    ],
    "priceDisplay": "contact",
    "currency": "GEL",
}


# --- ~8 destinations --------------------------------------------------------
DESTINATIONS = [
    ("mestia", "Mestia", (43.0458, 42.7288), 1500),
    ("ushguli", "Ushguli", (42.9167, 43.0167), 2100),
    ("koruldi-lakes", "Koruldi Lakes", (43.0700, 42.7100), 2700),
    ("chalaadi-glacier", "Chalaadi Glacier", (43.1200, 42.7700), 1900),
    ("mazeri", "Mazeri", (43.0500, 42.6200), 1600),
    ("shdugra-waterfall", "Shdugra Waterfall", (43.0600, 42.6100), 2000),
    ("adishi", "Adishi", (42.9500, 42.9000), 2000),
    ("tsvirmi", "Tsvirmi", (43.0000, 42.8300), 1750),
]

# --- 12 travel-guide article drafts ----------------------------------------
ARTICLES = [
    "Best Things to Do in Mestia",
    "Mestia to Ushguli: What Travelers Should Know",
    "Koruldi Lakes: Hiking and 4×4 Options",
    "Chalaadi Glacier Guide",
    "Mestia Without Hiking",
    "Family-Friendly Experiences in Svaneti",
    "What to Eat in Svaneti",
    "Mestia in Winter",
    "How to Reach Mestia",
    "Three Days in Svaneti",
    "Five Days in Svaneti",
    "What to Pack for Svaneti",
]

# --- ~10 FAQs ---------------------------------------------------------------
FAQS = [
    ("How do I get to Mestia?", "general",
     "Mestia is reached by road from Kutaisi, Zugdidi or Tbilisi, or by a "
     "seasonal flight to Mestia's small airport. Details are placeholders — "
     "confirm current options."),
    ("When is the best time to visit Svaneti?", "planning",
     "Summer and early autumn are most popular for hiking; winter suits skiing. "
     "Placeholder guidance."),
    ("Do I need a guide?", "planning",
     "A local guide helps with logistics, language and safety in the mountains. "
     "Placeholder guidance."),
    ("Are the tours family-friendly?", "tours",
     "Several experiences are suitable for families; look for the family flag. "
     "Placeholder guidance."),
    ("How much do tours cost?", "tours",
     "Prices are shown as 'contact for price' until confirmed. Placeholder."),
    ("What should I pack?", "planning",
     "Layers, rain protection and sturdy footwear. See the packing guide. "
     "Placeholder."),
    ("Is Svaneti safe?", "safety",
     "Svaneti is generally welcoming; mountain weather and terrain require care. "
     "Placeholder guidance."),
    ("What languages are spoken?", "general",
     "Georgian and Svan locally; guides may speak English and others. "
     "Placeholder — confirm languages."),
    ("Can dietary needs be accommodated?", "tours",
     "Often yes with notice; confirm when you inquire. Placeholder."),
    ("How do I book?", "booking",
     "Send an inquiry through the site and we will follow up. Placeholder."),
]

# --- Sample reviews (dev only, isSample=true) -------------------------------
SAMPLE_REVIEWS = [
    ("Sample Reviewer A", "SAMPLE", 5,
     "[SAMPLE REVIEW — not a real testimonial] A wonderful placeholder day."),
    ("Sample Reviewer B", "SAMPLE", 5,
     "[SAMPLE REVIEW — not a real testimonial] Placeholder feedback text."),
    ("Sample Reviewer C", "SAMPLE", 4,
     "[SAMPLE REVIEW — not a real testimonial] Example content only."),
]
