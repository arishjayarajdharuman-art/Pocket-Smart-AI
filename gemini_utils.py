import os
import re
import json
import urllib.parse
import warnings
from typing import Optional, Dict, Any, List

# Suppress library deprecation notices
warnings.filterwarnings("ignore")

from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# Gemini setup
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
genai_client = None

try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        genai_client = genai
except Exception as e:
    print(f"Warning: Could not configure google.generativeai: {e}")


def configure_api_key(api_key: str):
    global genai_client, GEMINI_API_KEY
    if not api_key:
        return False
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        GEMINI_API_KEY = api_key
        genai_client = genai
        return True
    except Exception as e:
        print(f"Error configuring API Key: {e}")
        return False


def get_available_gemini_model():
    """Return an available generative model instance"""
    if not genai_client or not GEMINI_API_KEY:
        return None
    
    # Preferred models ordered by capability
    preferred_models = [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-pro"
    ]
    for model_name in preferred_models:
        try:
            return genai.GenerativeModel(model_name)
        except Exception:
            continue
    return None


def extract_json_from_response(text: str) -> dict:
    """Extract clean JSON object from AI text response even if wrapped in markdown blocks"""
    try:
        # Try direct json loads first
        return json.loads(text.strip())
    except Exception:
        pass

    # Regex search for ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        clean_text = match.group(1).strip()
        try:
            return json.loads(clean_text)
        except Exception:
            pass

    # Fallback: search for first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    raise ValueError("Could not parse valid JSON from Gemini AI response")


# =====================================================================
# 1. HOME INTERIOR RECOMMENDATIONS
# =====================================================================

def get_home_recommendations(budget_input: Any) -> dict:
    """
    Generate home interior recommendations within budget for Indian market
    """
    total_budget = float(getattr(budget_input, 'total_budget', 50000))
    num_lights = int(getattr(budget_input, 'num_lights', 5))
    num_fans = int(getattr(budget_input, 'num_fans', 4))
    num_furniture = int(getattr(budget_input, 'num_furniture', 2))
    num_dining_tables = int(getattr(budget_input, 'num_dining_tables', 1))
    has_living_room = bool(getattr(budget_input, 'has_living_room', True))
    has_kitchen = bool(getattr(budget_input, 'has_kitchen', False))
    has_bedroom = bool(getattr(budget_input, 'has_bedroom', False))
    additional_req = getattr(budget_input, 'additional_requirements', None) or "None"

    # Rooms list
    rooms = []
    if has_living_room:
        rooms.append("Living room")
    if has_kitchen:
        rooms.append("Kitchen")
    if has_bedroom:
        rooms.append("Bedroom")
    rooms_str = ", ".join(rooms) if rooms else "General home space"

    prompt = f"""
I need interior design product recommendations for a home in India with a total budget of ₹{total_budget:.2f}.
Requirements:
- {num_lights} lights/lighting fixtures
- {num_fans} ceiling fans
- {num_furniture} furniture pieces
- {num_dining_tables} dining tables

Additional rooms to consider:
{'- Living room' if has_living_room else ''}
{'- Kitchen' if has_kitchen else ''}
{'- Bedroom' if has_bedroom else ''}

Additional requirements: {additional_req}

Please provide a detailed budget breakdown with product recommendations **available in India**.
Use **Indian brands and pricing**. Include **search terms** suitable for Indian shopping platforms.

Format your response as valid strictly parseable JSON with the following structure:
{{
  "total_budget": {total_budget:.2f},
  "remaining_budget": 0.0,
  "budget_breakdown": [
    {{
      "category": "Lighting",
      "allocation": 0.0,
      "items": [
        {{
          "name": "LED Warm White Ceiling Light",
          "description": "Energy-efficient 15W recessed LED panel lights for cozy ambiance.",
          "estimated_price": 0.0,
          "quantity": {num_lights if num_lights > 0 else 1},
          "search_terms": "LED warm white ceiling light Philips Wipro"
        }}
      ]
    }}

    
    
  ],
  "calculation_table": [
    {{
      "category": "Lighting",
      "items_count": {num_lights if num_lights > 0 else 1},
      "total_cost": 0.0,
      "percentage_of_budget": 0.0
    }}
  ],
  "additional_suggestions": [
    "Consider purchasing modular furniture for flexibility.",
    "Look for festive discounts and bundle deals on IKEA and Amazon India."
  ]
}}

Ensure all item prices and category allocations fit strictly within the total budget of ₹{total_budget:.2f}.
"""

    result = None
    model = get_available_gemini_model()
    if model:
        try:
            response = model.generate_content(prompt)
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Gemini home planner call failed: {e}. Using smart AI fallback engine.")
            result = None

    if not result:
        result = generate_smart_home_fallback(
            total_budget, num_lights, num_fans, num_furniture, num_dining_tables,
            has_living_room, has_kitchen, has_bedroom, additional_req
        )

    # Link shopping platforms
    category_list = result.get("budget_breakdown", [])
    total_spent = 0.0
    calc_table = []

    for category in category_list:
        cat_name = category.get("category", "General")
        cat_items = category.get("items", [])
        cat_cost = 0.0
        cat_count = 0

        for item in cat_items:
            price = float(item.get("estimated_price", 0.0))
            qty = int(item.get("quantity", 1))
            item_total = price * (qty if qty > 0 else 1)
            cat_cost += item_total
            cat_count += qty
            total_spent += item_total

            search_terms = item.get("search_terms") or item.get("name", "")
            encoded_query = urllib.parse.quote_plus(search_terms)

            item["shopping_links"] = {
                "amazon": f"https://www.amazon.in/s?k={encoded_query}",
                "flipkart": f"https://www.flipkart.com/search?q={encoded_query}",
                "ikea": f"https://www.ikea.com/in/en/search/?q={encoded_query}",
                "myntra": f"https://www.myntra.com/{encoded_query}",
                "ajio": f"https://www.ajio.com/search/?text={encoded_query}"
            }
        
        category["allocation"] = round(cat_cost, 2)
        pct = round((cat_cost / total_budget * 100), 1) if total_budget > 0 else 0
        calc_table.append({
            "category": cat_name,
            "items_count": cat_count,
            "total_cost": round(cat_cost, 2),
            "percentage_of_budget": pct
        })

    result["calculation_table"] = calc_table
    result["total_budget"] = total_budget
    result["remaining_budget"] = round(max(0.0, total_budget - total_spent), 2)
    return result


def generate_smart_home_fallback(total_budget: float, num_lights: int, num_fans: int,
                                 num_furniture: int, num_dining_tables: int,
                                 has_living: bool, has_kitchen: bool, has_bedroom: bool,
                                 additional_req: str) -> dict:
    """Smart algorithmic fallback for Home Interior Planner"""
    # Proportions based on input requirements
    weights = {}
    if num_lights > 0:
        weights["Lighting"] = 0.15
    if num_fans > 0:
        weights["Ceiling Fans"] = 0.20
    if num_furniture > 0:
        weights["Furniture & Seating"] = 0.35
    if num_dining_tables > 0:
        weights["Dining & Tables"] = 0.20
    if has_bedroom or has_kitchen:
        weights["Decor & Accents"] = 0.10

    if not weights:
        weights = {"Lighting": 0.25, "Furniture": 0.45, "Ceiling Fans": 0.15, "Decor": 0.15}

    total_weight = sum(weights.values())
    weights = {k: v / total_weight for k, v in weights.items()}

    breakdown = []
    
    if "Lighting" in weights:
        alloc = total_budget * weights["Lighting"]
        qty = max(1, num_lights if num_lights > 0 else 4)
        unit_price = round(alloc / (qty * 1.05), 2)
        breakdown.append({
            "category": "Lighting",
            "allocation": round(alloc, 2),
            "items": [
                {
                    "name": "Philips / Wipro Smart LED Batten & Recessed Fixtures",
                    "description": f"Energy-efficient warm white and cool daylight LED luminaires for optimal illumination.",
                    "estimated_price": unit_price,
                    "quantity": qty,
                    "search_terms": "Philips LED warm white ceiling fixtures"
                }
            ]
        })

    if "Ceiling Fans" in weights:
        alloc = total_budget * weights["Ceiling Fans"]
        qty = max(1, num_fans if num_fans > 0 else 2)
        unit_price = round(alloc / (qty * 1.05), 2)
        breakdown.append({
            "category": "Ceiling Fans",
            "allocation": round(alloc, 2),
            "items": [
                {
                    "name": "Havells / Atomberg BLDC Energy Saving Ceiling Fan",
                    "description": "5-star rated whisper-quiet BLDC motor ceiling fan with smart remote control.",
                    "estimated_price": unit_price,
                    "quantity": qty,
                    "search_terms": "Havells Atomberg BLDC ceiling fan"
                }
            ]
        })

    if "Furniture & Seating" in weights:
        alloc = total_budget * weights["Furniture & Seating"]
        qty = max(1, num_furniture if num_furniture > 0 else 2)
        unit_price = round(alloc / (qty * 1.05), 2)
        breakdown.append({
            "category": "Furniture",
            "allocation": round(alloc, 2),
            "items": [
                {
                    "name": "Modern Ergonomic Fabric Lounge Sofa / Chairs",
                    "description": "High-density foam comfortable cushions with solid engineered wood frame.",
                    "estimated_price": unit_price,
                    "quantity": qty,
                    "search_terms": "modern living room sofa set furniture"
                }
            ]
        })

    if "Dining & Tables" in weights:
        alloc = total_budget * weights["Dining & Tables"]
        qty = max(1, num_dining_tables if num_dining_tables > 0 else 1)
        unit_price = round(alloc / (qty * 1.05), 2)
        breakdown.append({
            "category": "Dining & Tables",
            "allocation": round(alloc, 2),
            "items": [
                {
                    "name": "Solid Wood 4-Seater Dining Table & Chair Set",
                    "description": "Compact minimalist Scandinavian styled dining set suitable for Indian family dining.",
                    "estimated_price": unit_price,
                    "quantity": qty,
                    "search_terms": "wooden 4 seater dining table set IKEA"
                }
            ]
        })

    if "Decor & Accents" in weights:
        alloc = total_budget * weights["Decor & Accents"]
        unit_price = round(alloc * 0.95, 2)
        breakdown.append({
            "category": "Decor & Accents",
            "allocation": round(alloc, 2),
            "items": [
                {
                    "name": "Ambient Wall Art & Indoor Planters Set",
                    "description": "Aesthetic framed canvas wall art pair with ceramic indoor plant pots.",
                    "estimated_price": unit_price,
                    "quantity": 1,
                    "search_terms": "modern minimalist framed wall art canvas"
                }
            ]
        })

    return {
        "total_budget": total_budget,
        "remaining_budget": 0.0,
        "budget_breakdown": breakdown,
        "additional_suggestions": [
            "Opt for multi-functional storage furniture to maximize floor space in Indian apartments.",
            "Mix warm 3000K accent lights with 4000K neutral ambient lighting for a cozy interior feel.",
            "Check IKEA India and Amazon Great Indian Festival for bundle discounts on matching collections.",
            "Prioritize BLDC ceiling fans to save up to 65% on monthly electricity bills."
        ]
    }


# =====================================================================
# 2. PARTY BUDGET RECOMMENDATIONS
# =====================================================================

def get_party_recommendations(budget_input: Any) -> dict:
    """
    Generate party planning recommendations within budget in INR for Indian market
    """
    total_budget = float(getattr(budget_input, 'total_budget', 30000))
    num_guests = int(getattr(budget_input, 'num_guests', 20))
    party_type = getattr(budget_input, 'party_type', 'Birthday') or 'Birthday'
    venue_type = getattr(budget_input, 'venue_type', 'Home') or 'Home'
    needs_catering = bool(getattr(budget_input, 'needs_catering', True))
    needs_decoration = bool(getattr(budget_input, 'needs_decoration', True))
    needs_entertainment = bool(getattr(budget_input, 'needs_entertainment', True))
    additional_req = getattr(budget_input, 'additional_requirements', None) or "None"

    prompt = f"""
I need party planning recommendations for India with a total budget of ₹{total_budget:.2f}.
Party details:
- Type: {party_type}
- Number of guests: {num_guests}
- Venue type: {venue_type}
- Catering needed: {"Yes" if needs_catering else "No"}
- Decoration needed: {"Yes" if needs_decoration else "No"}
- Entertainment needed: {"Yes" if needs_entertainment else "No"}
Additional requirements: {additional_req}

Please provide a detailed budget breakdown with specific recommendations available in India using INR prices.
Use Indian brands, services, and typical cost expectations.

Format your response as valid strictly parseable JSON with the following structure:
{{
  "total_budget": {total_budget:.2f},
  "remaining_budget": 0.0,
  "budget_breakdown": [
    {{
      "category": "venue",
      "allocation": 0.0,
      "items": [
        {{
          "name": "Venue Reservation / Setup",
          "description": "Space rental or home living room arrangement for {num_guests} guests.",
          "estimated_price": 0.0,
          "quantity": 1,
          "search_terms": "{venue_type} party hall {party_type}"
        }}
      ]
    }},
    {{
      "category": "catering",
      "allocation": 0.0,
      "items": [
        {{
          "name": "Buffet Catered Meal / Party Platter",
          "description": "Starters, Main course, Desserts and Beverages for {num_guests} guests.",
          "estimated_price": 0.0,
          "quantity": {num_guests},
          "search_terms": "party catering food boxes Swiggy Zomato"
        }}
      ]
    }},
    {{
      "category": "decoration",
      "allocation": 0.0,
      "items": [
        {{
          "name": "Themed Balloon Arch & Backdrop Kit",
          "description": "Customizable banner, metallic balloons, fairy lights and photo booth props.",
          "estimated_price": 0.0,
          "quantity": 1,
          "search_terms": "{party_type} theme decoration set balloon garland"
        }}
      ]
    }},
    {{
      "category": "entertainment",
      "allocation": 0.0,
      "items": [
        {{
          "name": "Party Games & Music Setup",
          "description": "Bluetooth party speaker rental, trivia games, and customized playlist curation.",
          "estimated_price": 0.0,
          "quantity": 1,
          "search_terms": "party games party bluetooth speaker karaoke"
        }}
      ]
    }},
    {{
      "category": "contingency",
      "allocation": 0.0,
      "items": [
        {{
          "name": "Emergency & Miscellaneous Buffer",
          "description": "Buffer for last minute extra guests, delivery charges, ice and cutlery.",
          "estimated_price": 0.0,
          "quantity": 1,
          "search_terms": "disposable party tableware biodegradable plates"
        }}
      ]
    }}
  ],
  "venue_suggestions": [
    {{
      "name": "Cozy Community Hall / Private Lounge",
      "type": "{venue_type}",
      "capacity": {max(num_guests + 10, 25)},
      "estimated_cost": 0.0,
      "search_terms": "{venue_type} banquet hall celebration spaces"
    }}
  ],
  "additional_suggestions": [
    "Opt for potluck or family-style buffet platters to optimize food wastage.",
    "Utilize DIY balloon arches from Amazon/Meesho to save on event planner labor fees.",
    "Order beverages in bulk from BigBasket or Blinkit for instant discounts."
  ]
}}

Ensure all costs are in INR and the sum of all item allocations does not exceed the total budget of ₹{total_budget:.2f}.
"""

    result = None
    model = get_available_gemini_model()
    if model:
        try:
            response = model.generate_content(prompt)
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Gemini party planner call failed: {e}. Using fallback generator.")
            result = None

    if not result:
        result = generate_smart_party_fallback(
            total_budget, num_guests, party_type, venue_type,
            needs_catering, needs_decoration, needs_entertainment, additional_req
        )

    # Category platform mappings according to specification
    category_platforms = {
        "venue": ["google", "booking", "makemytrip", "oyorooms", "nobroker"],
        "catering": ["swiggy", "zomato", "bigbasket"],
        "food": ["swiggy", "zomato", "bigbasket", "amazon", "flipkart"],
        "drinks": ["swiggy", "zomato", "bigbasket"],
        "decoration": ["amazon", "flipkart", "meesho", "myntra"],
        "entertainment": ["bookmyshow", "amazon", "flipkart"],
        "music": ["amazon", "flipkart", "bookmyshow"],
        "games": ["amazon", "flipkart"],
        "gifts": ["amazon", "flipkart", "myntra", "meesho"],
        "accessories": ["amazon", "flipkart", "myntra", "meesho"],
        "photography": ["google", "amazon", "flipkart"],
        "transportation": ["makemytrip", "google"],
        "return_gifts": ["amazon", "flipkart", "myntra", "meesho"],
        "contingency": ["amazon", "flipkart", "bigbasket"]
    }
    default_platforms = ["amazon", "flipkart", "google"]

    total_spent = 0.0
    calc_table = []

    for cat in result.get("budget_breakdown", []):
        cat_name = cat.get("category", "misc").lower()
        items = cat.get("items", [])
        cat_cost = 0.0
        cat_count = 0
        
        relevant_platforms = category_platforms.get(cat_name, default_platforms)

        for item in items:
            price = float(item.get("estimated_price", 0.0))
            qty = int(item.get("quantity", 1))
            item_total = price * (qty if qty > 0 else 1)
            cat_cost += item_total
            cat_count += qty
            total_spent += item_total

            search_terms = item.get("search_terms") or item.get("name", "")
            q = urllib.parse.quote_plus(search_terms)

            links = {}
            if "amazon" in relevant_platforms:
                links["amazon"] = f"https://www.amazon.in/s?k={q}"
            if "flipkart" in relevant_platforms:
                links["flipkart"] = f"https://www.flipkart.com/search?q={q}"
            if "swiggy" in relevant_platforms:
                links["swiggy"] = f"https://www.swiggy.com/search?query={q}"
            if "zomato" in relevant_platforms:
                links["zomato"] = f"https://www.zomato.com/search?q={q}"
            if "bigbasket" in relevant_platforms:
                links["bigbasket"] = f"https://www.bigbasket.com/ps/?q={q}"
            if "meesho" in relevant_platforms:
                links["meesho"] = f"https://www.meesho.com/search?q={q}"
            if "bookmyshow" in relevant_platforms:
                links["bookmyshow"] = f"https://in.bookmyshow.com/search?q={q}"
            if "makemytrip" in relevant_platforms:
                links["makemytrip"] = f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}"
            if "oyorooms" in relevant_platforms:
                links["oyorooms"] = f"https://www.oyorooms.com/search/?location={q}"
            if "nobroker" in relevant_platforms:
                links["nobroker"] = f"https://www.nobroker.in/property/search?searchTerm={q}"
            if "google" in relevant_platforms:
                links["google"] = f"https://www.google.com/search?q={q}"
            
            item["shopping_links"] = links

        cat["allocation"] = round(cat_cost, 2)
        pct = round((cat_cost / total_budget * 100), 1) if total_budget > 0 else 0
        calc_table.append({
            "category": cat.get("category", "General").title(),
            "items_count": cat_count,
            "total_cost": round(cat_cost, 2),
            "percentage_of_budget": pct
        })

    # Add venue search links
    for venue in result.get("venue_suggestions", []):
        v_terms = venue.get("search_terms") or venue.get("name", "")
        vq = urllib.parse.quote_plus(v_terms)
        venue["search_links"] = {
            "google": f"https://www.google.com/search?q={vq}",
            "booking": f"https://www.booking.com/search.html?ss={vq}",
            "makemytrip": f"https://www.makemytrip.com/hotels/hotel-listing/?searchText={vq}",
            "oyorooms": f"https://www.oyorooms.com/search/?location={vq}",
            "nobroker": f"https://www.nobroker.in/property/search?searchTerm={vq}"
        }

    result["calculation_table_inr"] = calc_table
    result["total_budget"] = total_budget
    result["remaining_budget"] = round(max(0.0, total_budget - total_spent), 2)
    return result


def generate_smart_party_fallback(total_budget: float, num_guests: int, party_type: str,
                                  venue_type: str, needs_catering: bool, needs_decoration: bool,
                                  needs_entertainment: bool, additional_req: str) -> dict:
    """Smart algorithmic fallback for Party Planner"""
    # Proportions
    cat_proportions = {}
    if venue_type.lower() != "home":
        cat_proportions["venue"] = 0.25
    else:
        cat_proportions["venue"] = 0.05

    if needs_catering:
        cat_proportions["catering"] = 0.45
    if needs_decoration:
        cat_proportions["decoration"] = 0.15
    if needs_entertainment:
        cat_proportions["entertainment"] = 0.10
    cat_proportions["contingency"] = 0.05

    total_p = sum(cat_proportions.values())
    cat_proportions = {k: v / total_p for k, v in cat_proportions.items()}

    breakdown = []
    
    # Venue
    v_alloc = round(total_budget * cat_proportions.get("venue", 0.1), 2)
    breakdown.append({
        "category": "venue",
        "allocation": v_alloc,
        "items": [
            {
                "name": f"{venue_type} Arrangement & Space Prep",
                "description": f"Seating arrangements, lighting ambient setup for {num_guests} guests.",
                "estimated_price": v_alloc,
                "quantity": 1,
                "search_terms": f"{venue_type} party hall rental {party_type}"
            }
        ]
    })

    # Catering
    if needs_catering:
        c_alloc = round(total_budget * cat_proportions.get("catering", 0.45), 2)
        per_guest = round(c_alloc / max(1, num_guests), 2)
        breakdown.append({
            "category": "catering",
            "allocation": c_alloc,
            "items": [
                {
                    "name": "Party Buffet & Welcome Drinks",
                    "description": f"Curated multi-course appetizers, main meal, and desserts for {num_guests} guests (approx ₹{per_guest}/person).",
                    "estimated_price": per_guest,
                    "quantity": num_guests,
                    "search_terms": f"party food catering platters {party_type}"
                }
            ]
        })

    # Decoration
    if needs_decoration:
        d_alloc = round(total_budget * cat_proportions.get("decoration", 0.15), 2)
        breakdown.append({
            "category": "decoration",
            "allocation": d_alloc,
            "items": [
                {
                    "name": f"{party_type} Metallic Balloons & Backdrop Kit",
                    "description": "Fairy string lights, photo backdrop banner, balloons, and cake table runner.",
                    "estimated_price": d_alloc,
                    "quantity": 1,
                    "search_terms": f"{party_type} celebration theme decoration kit"
                }
            ]
        })

    # Entertainment
    if needs_entertainment:
        e_alloc = round(total_budget * cat_proportions.get("entertainment", 0.10), 2)
        breakdown.append({
            "category": "entertainment",
            "allocation": e_alloc,
            "items": [
                {
                    "name": "Party Games & Music Playlist Sound System",
                    "description": "Interactive board games, karaoke mic / high-power party speaker rental.",
                    "estimated_price": e_alloc,
                    "quantity": 1,
                    "search_terms": "party games karaoke bluetooth speaker"
                }
            ]
        })

    # Contingency
    cont_alloc = round(total_budget * cat_proportions.get("contingency", 0.05), 2)
    breakdown.append({
        "category": "contingency",
        "allocation": cont_alloc,
        "items": [
            {
                "name": "Cutlery, Beverages & Emergency Buffer",
                "description": "Biodegradable tableware, extra ice, and buffer for miscellaneous expenses.",
                "estimated_price": cont_alloc,
                "quantity": 1,
                "search_terms": "disposable party tableware cups plates napkins"
            }
        ]
    })

    return {
        "total_budget": total_budget,
        "remaining_budget": 0.0,
        "budget_breakdown": breakdown,
        "venue_suggestions": [
            {
                "name": f"Selected {venue_type} Space",
                "type": venue_type,
                "capacity": max(num_guests + 10, 30),
                "estimated_cost": v_alloc,
                "search_terms": f"{venue_type} banquet hall celebration spaces"
            }
        ],
        "additional_suggestions": [
            "Consider ordering appetizers and main courses from Swiggy / Zomato party caterers for group discounts.",
            "Set up a DIY selfie booth with ring lights and props for memorable guest photos.",
            "Order snacks and soft drinks in bulk from BigBasket or Zepto ahead of time to save up to 20%."
        ]
    }


# =====================================================================
# 3. JEWELRY RECOMMENDATIONS (MULTIMODAL TEXT + IMAGE)
# =====================================================================

def get_jewelry_recommendations(budget_input: Any, image_path: Optional[str] = None) -> dict:
    """
    Generate jewelry recommendations based on uploaded dress and budget in INR (India-specific)
    Accepts text + image inputs.
    """
    total_budget = float(getattr(budget_input, 'total_budget', 25000))
    occasion = getattr(budget_input, 'occasion', 'Wedding') or 'Wedding'
    preferences = getattr(budget_input, 'preferences', None) or "Not specified"

    result = None
    model = get_available_gemini_model()

    base_prompt = f"""
I need jewelry recommendations for India with a total budget of ₹{total_budget:.2f}.
Occasion: {occasion}
Preferences: {preferences}
Provide only India-relevant styles, availability, and price ranges in INR.
"""

    if image_path and os.path.exists(image_path) and model:
        try:
            img = Image.open(image_path)
            multimodal_prompt = f"""{base_prompt}
An image of the outfit is uploaded. Suggest jewelry that complements it, considering color, design, neckline, and occasion appropriateness.

Format the output as strictly valid JSON:
{{
  "outfit_analysis": {{
    "colors": "e.g. Royal Blue & Gold",
    "style": "e.g. Traditional Banarasi Silk",
    "formality": "e.g. Formal Festive"
  }},
  "total_budget": {total_budget:.2f},
  "remaining_budget": 0.0,
  "jewelry_recommendations": [
    {{
      "item_type": "Necklace",
      "description": "22k Gold-plated Kundan choker with emerald bead drops.",
      "style": "Traditional Kundan",
      "estimated_price": 0.0,
      "search_terms": "gold plated kundan choker necklace set"
    }},
    {{
      "item_type": "Earrings",
      "description": "Matching Jhumkas with intricate meenakari work.",
      "style": "Meenakari Jhumka",
      "estimated_price": 0.0,
      "search_terms": "gold plated meenakari jhumka earrings"
    }},
    {{
      "item_type": "Bangles / Bracelet",
      "description": "Set of 2 embellished kada bangles with zircon accents.",
      "style": "Kada Bangle",
      "estimated_price": 0.0,
      "search_terms": "gold plated bridal kada bangles"
    }}
  ],
  "styling_tips": [
    "Pair the choker with a deep sweetheart or broad neckline for maximum elegance.",
    "Balance ornate earrings by keeping hair in an elegant updo or soft curls.",
    "Match metal undertones across necklace, bangles, and rings."
  ]
}}

Make sure prices are in INR and stay strictly within the budget. Include Indian-friendly search terms for shopping.
"""
            response = model.generate_content([multimodal_prompt, img])
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Multimodal jewelry generation failed: {e}. Trying text model or fallback.")
            result = None

    if not result and model:
        try:
            text_prompt = f"""{base_prompt}
Format the output as strictly valid JSON:
{{
  "outfit_analysis": {{
    "colors": "Coordinated with {occasion}",
    "style": "{preferences}",
    "formality": "Semi-formal to Formal"
  }},
  "total_budget": {total_budget:.2f},
  "remaining_budget": 0.0,
  "jewelry_recommendations": [
    {{
      "item_type": "Necklace / Pendant",
      "description": "Sterling silver / gold-toned designer pendant necklace.",
      "style": "Contemporary",
      "estimated_price": 0.0,
      "search_terms": "silver gold pendant necklace women"
    }},
    {{
      "item_type": "Earrings",
      "description": "Sparkling stud / drop earrings to complement the neckline.",
      "style": "Elegance",
      "estimated_price": 0.0,
      "search_terms": "designer drop earrings women"
    }},
    {{
      "item_type": "Bracelet / Ring",
      "description": "Minimalist adjustable cuff bracelet or solitaire ring.",
      "style": "Minimalist",
      "estimated_price": 0.0,
      "search_terms": "minimalist silver bracelet adjustable"
    }}
  ],
  "styling_tips": [
    "Choose jewelry that emphasizes your natural neckline and dress color.",
    "Keep pieces cohesive in finish (e.g. all rose gold, yellow gold, or silver)."
  ]
}}
Keep prices in INR and relevant to Indian brands.
"""
            response = model.generate_content(text_prompt)
            result = extract_json_from_response(response.text)
        except Exception as e:
            print(f"Text jewelry generation failed: {e}. Using fallback.")
            result = None

    if not result:
        result = generate_smart_jewelry_fallback(total_budget, occasion, preferences, image_path)

    # Link shopping platforms for Indian jewelry stores
    total_spent = 0.0
    items = result.get("jewelry_recommendations", [])
    for item in items:
        price = float(item.get("estimated_price", 0.0))
        total_spent += price
        search_terms = item.get("search_terms") or item.get("item_type", "")
        q = urllib.parse.quote_plus(search_terms)

        item["shopping_links"] = {
            "amazon": f"https://www.amazon.in/s?k={q}",
            "flipkart": f"https://www.flipkart.com/search?q={q}",
            "bluestone": f"https://www.bluestone.com/search.html?query={q}",
            "tanishq": f"https://www.tanishq.co.in/search?q={q}",
            "caratlane": f"https://www.caratlane.com/search?q={q}",
            "melorra": f"https://www.melorra.com/search?q={q}",
            "meesho": f"https://www.meesho.com/search?q={q}"
        }

    result["total_budget"] = total_budget
    result["remaining_budget"] = round(max(0.0, total_budget - total_spent), 2)
    return result


def generate_smart_jewelry_fallback(total_budget: float, occasion: str, preferences: str, image_path: Optional[str]) -> dict:
    """Smart algorithmic fallback for Jewelry Planner"""
    neck_price = round(total_budget * 0.45, 2)
    ear_price = round(total_budget * 0.30, 2)
    brace_price = round(total_budget * 0.20, 2)

    has_img = bool(image_path)

    return {
        "total_budget": total_budget,
        "remaining_budget": round(total_budget - (neck_price + ear_price + brace_price), 2),
        "outfit_analysis": {
            "colors": "Vibrant festive shades" if "wedding" in occasion.lower() else "Elegant harmonized tones",
            "style": preferences if preferences and preferences != "Not specified" else "Classic contemporary",
            "formality": "High Glamour / Formal" if "wedding" in occasion.lower() else "Chic Festive"
        },
        "jewelry_recommendations": [
            {
                "item_type": "Necklace Set",
                "description": f"Exquisite designer necklace crafted for {occasion} with fine gemstone embellishments.",
                "style": "Royal Contemporary",
                "estimated_price": neck_price,
                "search_terms": f"designer necklace set {occasion}"
            },
            {
                "item_type": "Statement Earrings",
                "description": f"Handcrafted chandelier earrings / jhumkas complementing the outfit silhouette.",
                "style": "Statement Elegance",
                "estimated_price": ear_price,
                "search_terms": f"statement chandelier jhumka earrings {occasion}"
            },
            {
                "item_type": "Cuff Bracelet / Kada",
                "description": "Polished adjustable bracelet with micro-pave stone accents.",
                "style": "Modern Luxury",
                "estimated_price": brace_price,
                "search_terms": f"women luxury bracelet bangle {occasion}"
            }
        ],
        "styling_tips": [
            f"For a {occasion}, coordinate your metal finish (yellow gold, white gold, rose gold) with any embroidery on your dress.",
            "If wearing an ornate statement necklace, opt for understated stud or drop earrings to keep the look balanced.",
            "Layer delicate chain bracelets or stick to a single focal kada on your non-dominant wrist.",
            "Shop on Tanishq, CaratLane, BlueStone and Amazon for authentic hallmarked designs with certified hallmarks."
        ]
    }


if __name__ == "__main__":
    print("==================================================")
    print("PocketSmart AI - Gemini AI Engine & Fallback Unit")
    print("==================================================")
    api_status = "Configured" if GEMINI_API_KEY else "Not set (using AI Fallback Engine)"
    print(f"API Key Status: {api_status}")
    print("\nTo launch the complete Web Application, run:")
    print("  python app.py")
    print("  or double-click run.bat")
    print("==================================================")
