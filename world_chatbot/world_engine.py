import json
import os
import shlex
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
WORLD_FILE = os.path.join(DATA_DIR, "worlds.json")
HOME_FILE = os.path.join(DATA_DIR, "homes.json")
USER_FILE = os.path.join(DATA_DIR, "users.json")
SEED_FILE = os.path.join(DATA_DIR, "seed_worlds.json")


def _ensure_data_files() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(WORLD_FILE) or not os.path.exists(HOME_FILE):
        # Seed from bundled seed file.
        seed = {"worlds": [], "homes": []}
        if os.path.exists(SEED_FILE):
            with open(SEED_FILE, "r", encoding="utf-8") as f:
                try:
                    seed = json.load(f)
                except Exception:
                    seed = {"worlds": [], "homes": []}
        worlds = seed.get("worlds", [])
        homes = seed.get("homes", [])

        with open(WORLD_FILE, "w", encoding="utf-8") as f:
            json.dump({"worlds": worlds}, f, indent=2, ensure_ascii=False)
        with open(HOME_FILE, "w", encoding="utf-8") as f:
            json.dump({"homes": homes}, f, indent=2, ensure_ascii=False)

    if not os.path.exists(USER_FILE):
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": {}}, f, indent=2, ensure_ascii=False)


def _load_users() -> Dict[str, Any]:
    _ensure_data_files()
    with open(USER_FILE, "r", encoding="utf-8") as f:
        obj = json.load(f)
    u = obj.get("users")
    return u if isinstance(u, dict) else {}


def _save_users(users: Dict[str, Any]) -> None:
    _ensure_data_files()
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": users}, f, indent=2, ensure_ascii=False)


def _load_json(path: str, key: str) -> List[Dict[str, Any]]:
    _ensure_data_files()
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj.get(key, [])


def _save_json(path: str, key: str, items: List[Dict[str, Any]]) -> None:
    _ensure_data_files()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({key: items}, f, indent=2, ensure_ascii=False)


def list_worlds() -> List[Dict[str, Any]]:
    return _load_json(WORLD_FILE, "worlds")


def list_homes() -> List[Dict[str, Any]]:
    return _load_json(HOME_FILE, "homes")


def _next_id(prefix: str, existing_ids: List[str]) -> str:
    # IDs are like W001, H012...
    nums = []
    for x in existing_ids:
        m = re.match(r"^" + re.escape(prefix) + r"(\d{3,})$", str(x))
        if m:
            try:
                nums.append(int(m.group(1)))
            except ValueError:
                pass
    n = (max(nums) if nums else 0) + 1
    return f"{prefix}{n:03d}"


def create_world(world: Dict[str, Any]) -> Dict[str, Any]:
    worlds = list_worlds()
    new_id = _next_id("W", [w.get("id", "") for w in worlds])
    world = {**world}
    world["id"] = new_id
    # Access controls
    world.setdefault("visibility", "public")  # public | private
    world.setdefault("allowed_users", [])
    worlds.append(world)
    _save_json(WORLD_FILE, "worlds", worlds)
    return world


def create_home(home: Dict[str, Any]) -> Dict[str, Any]:
    homes = list_homes()
    new_id = _next_id("H", [h.get("id", "") for h in homes])
    home = {**home}
    home["id"] = new_id
    homes.append(home)
    _save_json(HOME_FILE, "homes", homes)
    return home


def home_ascii_layout(home_id_or_name: str) -> Optional[str]:
    h = get_home(home_id_or_name)
    if not h:
        return None
    name = h.get("name", "Home")
    style = h.get("style", "?")
    size = h.get("size", "?")
    theme = h.get("theme", "?")
    return (
        f"┌──────────────────────────────────────────────┐\n"
        f"│  🏠 HOME: {name[:34]:34} │\n"
        f"├──────────────────────────────────────────────┤\n"
        f"│  style: {style:12} size: {size:12}          │\n"
        f"│  theme: {theme:29} │\n"
        f"├──────────────────────────────────────────────┤\n"
        f"│  ┌──────────┐   ┌──────────┐               │\n"
        f"│  │  STUDY   │   │  KITCHEN │               │\n"
        f"│  └────┬─────┘   └────┬─────┘               │\n"
        f"│       │   ┌──────────┴─────────┐           │\n"
        f"│       └───│   GREAT ROOM / HUB  │           │\n"
        f"│           └───────┬─────────────┘           │\n"
        f"│                   │                         │\n"
        f"│            ┌──────┴──────┐                  │\n"
        f"│            │  BED / NEST  │                  │\n"
        f"│            └──────────────┘                  │\n"
        f"└──────────────────────────────────────────────┘\n"
        f"Tip: click a Home card to auto-fill !home stats <id>"
    )


def get_world(world_id_or_name: str) -> Optional[Dict[str, Any]]:
    s = world_id_or_name.strip()
    for w in list_worlds():
        if w.get("id", "").lower() == s.lower() or w.get("name", "").lower() == s.lower():
            return w
    return None


def get_home(home_id_or_name: str) -> Optional[Dict[str, Any]]:
    s = home_id_or_name.strip()
    for h in list_homes():
        if h.get("id", "").lower() == s.lower() or h.get("name", "").lower() == s.lower():
            return h
    return None


def world_stats(world_id_or_name: str) -> Optional[str]:
    w = get_world(world_id_or_name)
    if not w:
        return None
    lines = [
        f"{w.get('id','?')} — {w.get('name','(unnamed)')}",
        f"Biome: {w.get('biome','?')} | Climate: {w.get('climate','?')}",
        f"Magic: {w.get('magic','?')} | Tech: {w.get('tech','?')}",
        f"Governance: {w.get('governance','?')} | Economy: {w.get('economy','?')}",
        f"Danger: {w.get('danger','?')} | Mood: {w.get('mood','?')}",
        f"Population: {w.get('population','?')}"
    ]
    lm = w.get("landmarks") or []
    if isinstance(lm, list) and lm:
        lines.append("Landmarks: " + ", ".join(map(str, lm[:6])))
    tags = w.get("tags") or []
    if isinstance(tags, list) and tags:
        lines.append("Tags: " + ", ".join(map(str, tags[:10])))
    return "\n".join(lines)


def world_population(world_id_or_name: Optional[str] = None) -> str:
    worlds = list_worlds()
    if world_id_or_name:
        w = get_world(world_id_or_name)
        if not w:
            return "World not found. Try !world list"
        return f"{w.get('id','?')} {w.get('name','(unnamed)')}: population {w.get('population','?')}"

    total = 0
    rows = []
    for w in worlds:
        pop = w.get("population")
        try:
            pop_i = int(pop)
        except Exception:
            pop_i = 0
        total += pop_i
        rows.append(f"{w.get('id','?')} {w.get('name','(unnamed)')}: {pop}")
    rows.append(f"TOTAL population (sum of numeric values): {total}")
    return "\n".join(rows)


def ascii_map(world_id_or_name: str) -> Optional[str]:
    w = get_world(world_id_or_name)
    if not w:
        return None
    name = w.get("name", "World")
    biome = w.get("biome", "?")
    mood = w.get("mood", "?")
    # Lightweight ASCII map.
    return (
        f"┌──────────────────────────────────────────────┐\n"
        f"│  🗺️  MAP: {name[:34]:34} │\n"
        f"├──────────────────────────────────────────────┤\n"
        f"│  Biome: {biome:10}   Mood: {mood:18} │\n"
        f"│                                              │\n"
        f"│   🌲🌲🌲🌲   ~~~ river ~~~      🏠🏠          │\n"
        f"│   🌲  ⛰️  🌲     ║ bridge ║     🏠            │\n"
        f"│   🌲🌲🌲🌲        ║        ║                  │\n"
        f"│            ✨ grove        🏰 keep           │\n"
        f"│                                              │\n"
        f"└──────────────────────────────────────────────┘\n"
        f"Tip: add homes with !create home or !home create --world {w.get('id','W???')} ..."
    )


HELP_TEXT = """\
Sentinel World Chatbot — Command Reference

Core
  !help                      Show this help
  !users                     Show connected users (this room)
  !ping                      Quick check (bot replies)

Worlds
  !world list                 List all worlds
  !stats <world>              Show stats for a world (ID or exact name)
  !population [world]         Show population for one world or all worlds
  !map <world>                Show a simple ASCII map for a world

Create (Interactive)
  !create world               Starts the World Builder wizard
  !create home                Starts the Home Builder wizard

Create (Manual / Non-interactive)
  !world create --name "Name" --biome forest --climate temperate --magic high --tech low \
               --governance council --economy "craft + trade" --danger low --mood calm --population 1200

  !home create --name "Name" --world W001 --style cottage --size small --theme cozy --security low \
              --materials "stone, cedar" --amenities "fireplace, garden"

Wizard Difficulties (World Builder)
  Beginner: 10 questions (each has 10 options)
  Medium:   20 questions (each has 10 options)
  Advanced: 30 questions (each has 10 options)

Notes
- IDs are auto-assigned: worlds W001, W002... homes H001, H002...
- This room is a single shared chatroom.
- Anything that doesn't start with ! is treated as a normal chat message.
"""


QUESTION_BANK: Dict[str, List[Dict[str, Any]]] = {
    "beginner": [],
    "medium": [],
    "advanced": [],
}


def _q(text: str, options: List[str], field: str) -> Dict[str, Any]:
    return {"text": text, "options": options, "field": field}


def _build_question_bank() -> None:
    # 10 options for each question.
    biomes = ["forest", "desert", "tundra", "ocean", "jungle", "mountain", "swamp", "plains", "city", "sky-islands"]
    climates = ["temperate", "arid", "humid", "polar", "monsoon", "mediterranean", "stormy", "dry-cold", "misty", "variable"]
    magic_levels = ["none", "low", "mid", "high", "wild", "ritual", "psychic", "tech-magic", "ancient", "forbidden"]
    tech_levels = ["stone", "iron", "medieval", "renaissance", "industrial", "modern", "near-future", "spacefaring", "post-scarcity", "ruins"]
    governance = ["council", "monarchy", "guilds", "democracy", "theocracy", "tribes", "AI steward", "anarchy", "imperial", "caretakers"]
    economy = ["agrarian", "craft", "trade", "mining", "research", "tourism", "alchemy", "data", "salvage", "gift"]
    danger = ["very low", "low", "moderate", "high", "extreme", "unknown", "cosmic", "political", "nature", "monsters"]
    mood = ["welcoming", "mysterious", "serene", "tense", "joyful", "somber", "heroic", "haunted", "playful", "sacred"]
    main_species = ["humans", "elves", "dwarves", "androids", "spirits", "beastfolk", "dragons", "merfolk", "aliens", "mixed"]
    sky = ["clear", "aurora", "two moons", "ringed planet", "storm-bands", "endless twilight", "crystal stars", "black sun", "nebula", "shifting"]

    base10 = [
        _q("Choose a biome", biomes, "biome"),
        _q("Choose a climate", climates, "climate"),
        _q("Magic level", magic_levels, "magic"),
        _q("Technology level", tech_levels, "tech"),
        _q("Governance style", governance, "governance"),
        _q("Primary economy", economy, "economy"),
        _q("Overall danger", danger, "danger"),
        _q("World mood", mood, "mood"),
        _q("Main people/species", main_species, "species"),
        _q("Sky feature", sky, "sky"),
    ]

    # Expand to 20 / 30 by adding more flavor axes.
    factions = ["Lantern Order", "Iron Guild", "Garden Circle", "Starwatch", "River Traders", "Ash Monks", "Clockwork House", "Glass Choir", "Wanderers", "Sentinels"]
    hazards = ["bandits", "storms", "curses", "wild magic", "radiation", "quakes", "floods", "political intrigue", "plague", "sleep-dream rifts"]
    resources = ["timber", "ore", "herbs", "crystals", "fish", "data", "spice", "energy", "ancient relics", "fresh water"]
    travel = ["roads", "airships", "portals", "riverboats", "rails", "beasts", "teleport nodes", "sand skiffs", "submersibles", "walking paths"]
    art = ["music", "mosaics", "tattoos", "calligraphy", "theatre", "sculpture", "weaving", "holograms", "storyfire", "gardens"]
    holidays = ["Lantern Night", "First Bloom", "Skyfall", "Forgeweek", "Quiet Tide", "Clockturn", "Moon Chorus", "Harvest Oath", "Snow Ember", "Waking Day"]
    law = ["strict", "balanced", "lenient", "ritual", "code-of-honor", "contract", "oracle", "AI rules", "customs", "no law"]
    outsiders = ["welcome", "tested", "watched", "taxed", "ignored", "celebrated", "feared", "barred", "recruited", "adopted"]
    aesthetics = ["cozy", "gothic", "solar", "rustic", "neon", "baroque", "minimal", "mushroom", "ice", "volcanic"]
    animals = ["owls", "wolves", "serpents", "foxes", "whales", "frogs", "spiders", "ravens", "butterflies", "dragons"]

    extra10 = [
        _q("Dominant faction", factions, "faction"),
        _q("Main hazard", hazards, "hazard"),
        _q("Key resource", resources, "resource"),
        _q("Common travel", travel, "travel"),
        _q("Art style", art, "art"),
        _q("Major holiday", holidays, "holiday"),
        _q("Law style", law, "law"),
        _q("Outsiders are...", outsiders, "outsiders"),
        _q("Aesthetic vibe", aesthetics, "aesthetic"),
        _q("Iconic creature", animals, "creature"),
    ]

    # Final 10 for advanced.
    seasons = ["4 seasons", "2 seasons", "endless summer", "endless winter", "wandering seasons", "storm season", "dry season", "bloom season", "twilight season", "unknown"]
    currency = ["coins", "barter", "tokens", "credit", "shells", "runes", "stamps", "favor", "time", "no currency"]
    religion = ["none", "ancestor", "nature", "star", "machine", "many gods", "one god", "mystery", "dream", "forbidden"]
    food = ["berries", "bread", "spice stew", "seaweed", "mushrooms", "honey", "synthetic", "smoked fish", "tea", "feast"]
    tone = ["hopeful", "grim", "adventurous", "romantic", "surreal", "whimsical", "noir", "epic", "slice-of-life", "mythic"]
    threat = ["none", "rival realm", "ancient beast", "AI uprising", "dream leak", "war", "hunger", "curse", "void", "time fracture"]
    magic_source = ["ley lines", "spirits", "runes", "tech", "blood", "song", "stars", "dreams", "books", "unknown"]
    defense = ["walls", "wards", "watchtowers", "drones", "rangers", "guardians", "pacts", "camouflage", "no defenses", "dragons"]
    portal = ["none", "one gate", "many gates", "hidden doors", "mirror paths", "phone-lines", "cloud tunnels", "river locks", "tree steps", "dream doors"]
    secret = ["lost library", "hidden city", "buried machine", "royal scandal", "alien signal", "seed vault", "time vault", "ghost network", "cursed crown", "open secret"]

    extra20 = [
        _q("Season pattern", seasons, "seasons"),
        _q("Currency", currency, "currency"),
        _q("Belief system", religion, "belief"),
        _q("Signature food", food, "food"),
        _q("Story tone", tone, "tone"),
        _q("Biggest threat", threat, "threat"),
        _q("Magic source", magic_source, "magic_source"),
        _q("Defenses", defense, "defense"),
        _q("Portals", portal, "portals"),
        _q("Hidden secret", secret, "secret"),
    ]

    QUESTION_BANK["beginner"] = base10
    QUESTION_BANK["medium"] = base10 + extra10
    QUESTION_BANK["advanced"] = base10 + extra10 + extra20


_build_question_bank()


HOME_QUESTIONS = [
    _q("Home style", ["cottage", "apartment", "tower", "cabin", "villa", "longhouse", "ship-home", "treehouse", "bunker", "mansion"], "style"),
    _q("Home size", ["tiny", "small", "medium", "large", "grand", "sprawling", "hidden", "vertical", "underground", "floating"], "size"),
    _q("Decor theme", ["cozy", "minimal", "gothic", "rustic", "neon", "natural", "arcane", "industrial", "royal", "kids-creative"], "theme"),
    _q("Primary material", ["wood", "stone", "brick", "glass", "steel", "bone", "crystal", "clay", "ice", "living-vines"], "materials"),
    _q("Security", ["none", "low", "mid", "high", "wards", "traps", "guards", "drones", "hidden", "dragon"], "security"),
    _q("Signature amenity", ["garden", "library", "workshop", "observatory", "fireplace", "pool", "forge", "lab", "music-room", "portal-door"], "amenities"),
]


@dataclass
class WizardState:
    mode: str  # 'world' or 'home'
    difficulty: str
    step: int
    answers: Dict[str, Any]
    name: Optional[str] = None


def wizard_start(mode: str, difficulty: str, name: Optional[str] = None) -> WizardState:
    difficulty = difficulty.lower().strip()
    if mode == "world" and difficulty not in QUESTION_BANK:
        difficulty = "beginner"
    if mode == "home":
        difficulty = "home"
    return WizardState(mode=mode, difficulty=difficulty, step=0, answers={}, name=name)


def wizard_question(state: WizardState) -> Tuple[str, List[str]]:
    if state.mode == "world":
        qs = QUESTION_BANK[state.difficulty]
    else:
        qs = HOME_QUESTIONS

    if state.step >= len(qs):
        return ("(done)", [])

    q = qs[state.step]
    text = q["text"]
    opts = q["options"]

    prompt_lines = [f"{text} — choose 1-10"]
    for i, opt in enumerate(opts, start=1):
        prompt_lines.append(f"  {i}. {opt}")
    return ("\n".join(prompt_lines), opts)


def wizard_apply_answer(state: WizardState, raw: str) -> Tuple[WizardState, Optional[str]]:
    raw = raw.strip()
    if raw.lower() in {"cancel", "!cancel", "stop", "quit"}:
        return state, "Wizard cancelled."

    if state.mode == "world":
        qs = QUESTION_BANK[state.difficulty]
    else:
        qs = HOME_QUESTIONS

    if state.step >= len(qs):
        return state, None

    q = qs[state.step]
    opts = q["options"]
    field = q["field"]

    try:
        idx = int(raw)
    except ValueError:
        return state, "Please answer with a number 1-10 (or type cancel)."

    if not (1 <= idx <= 10):
        return state, "Please pick a number from 1 to 10 (or type cancel)."

    chosen = opts[idx - 1]
    state.answers[field] = chosen
    state.step += 1
    return state, None


def wizard_finalize(state: WizardState) -> Dict[str, Any]:
    if state.mode == "world":
        world = {
            "name": state.name or "Untitled World",
            "biome": state.answers.get("biome"),
            "climate": state.answers.get("climate"),
            "magic": state.answers.get("magic"),
            "tech": state.answers.get("tech"),
            "governance": state.answers.get("governance"),
            "economy": state.answers.get("economy"),
            "danger": state.answers.get("danger"),
            "mood": state.answers.get("mood"),
            "population": int(state.answers.get("population", 1000)) if str(state.answers.get("population", "")).isdigit() else 1000,
            "tags": [state.difficulty, "wizard"],
            "landmarks": [
                f"{state.answers.get('aesthetic','') or 'Lantern'} Plaza",
                f"{state.answers.get('creature','') or 'Owl'} Hollow",
                f"{state.answers.get('secret','') or 'Hidden'} Archive",
            ],
            "wizard": {"difficulty": state.difficulty, "answers": state.answers},
        }
        return create_world(world)

    # home
    home = {
        "name": state.name or "Untitled Home",
        "world": state.answers.get("world"),
        "style": state.answers.get("style"),
        "size": state.answers.get("size"),
        "theme": state.answers.get("theme"),
        "materials": state.answers.get("materials"),
        "security": state.answers.get("security"),
        "amenities": state.answers.get("amenities"),
        "wizard": {"answers": state.answers},
    }
    return create_home(home)


def home_stats(home_id_or_name: str) -> Optional[str]:
    h = get_home(home_id_or_name)
    if not h:
        return None
    lines = [
        f"{h.get('id','?')} — {h.get('name','(unnamed)')}",
        f"World: {h.get('world','?')} | Style: {h.get('style','?')} | Size: {h.get('size','?')}",
        f"Theme: {h.get('theme','?')} | Materials: {h.get('materials','?')} | Security: {h.get('security','?')}",
        f"Amenity: {h.get('amenities','?')}",
    ]
    return "\n".join(lines)


def ascii_home(home_id_or_name: str) -> Optional[str]:
    h = get_home(home_id_or_name)
    if not h:
        return None
    name = h.get("name", "Home")
    style = h.get("style", "?")
    theme = h.get("theme", "?")
    # Tiny schematic (flavor, not to scale)
    return (
        f"┌──────────────────────────────────────────────┐\n"
        f"│  🏠  HOME: {name[:34]:34} │\n"
        f"├──────────────────────────────────────────────┤\n"
        f"│  Style: {style:10}  Theme: {theme:18} │\n"
        f"│                                              │\n"
        f"│   ┌──────────┐  ┌──────────┐                │\n"
        f"│   │  entry   │  │  hearth  │                │\n"
        f"│   └────┬─────┘  └────┬─────┘                │\n"
        f"│        │             │                      │\n"
        f"│   ┌────▼─────┐  ┌────▼─────┐                │\n"
        f"│   │  rest    │  │  work    │                │\n"
        f"│   └──────────┘  └──────────┘                │\n"
        f"│                                              │\n"
        f"└──────────────────────────────────────────────┘\n"
        f"Tip: create more with !create home or !home create --name \"...\" --world {h.get('world','W???')} ..."
    )


def _world_access(world: Dict[str, Any], user: str) -> bool:
    # Default is public.
    vis = str(world.get("visibility", "public")).lower()
    owner = str(world.get("owner", ""))
    allow = world.get("allowed_users") or []
    if user and owner and user == owner:
        return True
    if vis == "public":
        return True
    if isinstance(allow, list) and user in allow:
        return True
    return False


def _parse_kv_flags(tokens: List[str]) -> Dict[str, Any]:
    """Parse CLI-like --key value pairs. Values may be quoted due to shlex."""
    out: Dict[str, Any] = {}
    key = None
    for t in tokens:
        if t.startswith("--"):
            key = t[2:]
            out[key] = True
        elif key:
            out[key] = t
            key = None
    return out


class Engine:
    """Command engine used by app.py.

    Implements:
    - per-user profiles (selected world)
    - owner permissions + world access locks
    - interactive wizards for world/home creation
    """

    def __init__(self) -> None:
        self._wizard: Dict[str, WizardState] = {}

    def _world_update(self, world_id: str, **updates: Any) -> Optional[Dict[str, Any]]:
        worlds = list_worlds()
        for i, w in enumerate(worlds):
            if str(w.get("id")) == str(world_id):
                w = {**w, **updates}
                worlds[i] = w
                _save_json(WORLD_FILE, "worlds", worlds)
                return w
        return None

    def now_ms(self) -> int:
        # Frontend uses this for timestamps.
        import time

        return int(time.time() * 1000)

    def wizard_active(self, sid: str) -> bool:
        return sid in self._wizard

    def _profile_get(self, user: str) -> Dict[str, Any]:
        users = _load_users()
        prof = users.get(user) if isinstance(users, dict) else None
        if not isinstance(prof, dict):
            prof = {"selected_world": None}
            users[user] = prof
            _save_users(users)
        return prof

    def _profile_set(self, user: str, **kwargs: Any) -> None:
        users = _load_users()
        prof = users.get(user)
        if not isinstance(prof, dict):
            prof = {}
        prof.update(kwargs)
        users[user] = prof
        _save_users(users)

    def state_payload(self, user: str) -> Dict[str, Any]:
        # Only show accessible worlds/homes.
        worlds = [w for w in list_worlds() if _world_access(w, user)]
        world_ids = {w.get("id") for w in worlds}
        homes = [h for h in list_homes() if h.get("world") in world_ids]
        return {"worlds": worlds, "homes": homes}

    def handle_input(self, sid: str, user: str, text: str, online_users: List[str]) -> Tuple[List[Dict[str, Any]], bool]:
        text = (text or "").strip()
        msgs: List[Dict[str, Any]] = []
        state_changed = False

        # Wizard flow
        if sid in self._wizard and (not text.startswith("!") or text.lower() in {"!cancel", "cancel", "!back", "back"}):
            st = self._wizard[sid]
            if text.lower() in {"!back", "back"}:
                st.step = max(0, st.step - 1)
                q, _ = wizard_question(st)
                self._wizard[sid] = st
                return ([{"user": "Builder", "body": "⬅️  Went back one step.\n" + q, "kind": "system"}], False)
            st, err = wizard_apply_answer(st, text)
            if err:
                return ([{"user": "Builder", "body": err, "kind": "system"}], False)
            q, _ = wizard_question(st)
            self._wizard[sid] = st
            if q != "(done)":
                return ([{"user": "Builder", "body": q, "kind": "system"}], False)

            # finalize
            created = wizard_finalize(st)
            self._wizard.pop(sid, None)
            state_changed = True
            if st.mode == "world":
                # Persist owner/locks
                updated = self._world_update(
                    created.get("id", ""),
                    owner=user,
                    visibility=str(created.get("visibility", "public")) or "public",
                    allowed_users=list(set((created.get("allowed_users") or []) + [user])),
                )
                if updated:
                    created = updated
                msgs.append({"user": "Builder", "body": f"✅ World created: {created.get('id')} — {created.get('name')} (owner: {user})", "kind": "system"})
            else:
                msgs.append({"user": "Builder", "body": f"✅ Home created: {created.get('id')} — {created.get('name')} (world: {created.get('world')})", "kind": "system"})
            return (msgs, state_changed)

        if not text.startswith("!"):
            return ([{"user": "System", "body": "(internal) expected a command or wizard answer", "kind": "system"}], False)

        # Command parsing
        try:
            tokens = shlex.split(text)
        except Exception:
            tokens = text.split()

        cmd = tokens[0].lower()
        args = tokens[1:]

        if cmd in {"!help", "!h"}:
            msgs.append({"user": "Help", "body": HELP_TEXT + "\n\nExtras\n  !select world <id|name>       Set your default world\n  !world lock <id> public|private\n  !world allow <id> add|remove <username>\n  !home list                     List homes (accessible)\n  !home stats <home>             Stats for a home\n  !home map <home>               ASCII home diagram\n", "kind": "system"})
            return (msgs, False)

        if cmd == "!ping":
            return ([{"user": "System", "body": "pong ✅", "kind": "system"}], False)

        if cmd == "!users":
            return ([{"user": "System", "body": "Users online: " + ", ".join(online_users), "kind": "system"}], False)

        if (cmd == "!world" and args[:1] == ["list"]) or cmd == "!worldlist" or text.lower() == "!world list":
            worlds = [w for w in list_worlds() if _world_access(w, user)]
            if not worlds:
                return ([{"user": "System", "body": "No worlds found.", "kind": "system"}], False)
            lines = ["Worlds:"]
            for w in worlds:
                vis = w.get("visibility", "public")
                owner = w.get("owner", "")
                lines.append(f"- {w.get('id')} — {w.get('name')} (biome={w.get('biome')}, magic={w.get('magic')}, pop={w.get('population')}, {vis}, owner={owner})")
            return ([{"user": "System", "body": "\n".join(lines), "kind": "system"}], False)

        if (cmd == "!home" and args[:1] == ["list"]) or text.lower() == "!home list":
            payload = self.state_payload(user=user)
            homes = payload.get("homes", [])
            if not homes:
                return ([{"user": "System", "body": "No accessible homes yet.", "kind": "system"}], False)
            lines = ["Homes:"]
            for h in homes:
                lines.append(f"- {h.get('id')} — {h.get('name')} (world={h.get('world')}, style={h.get('style')}, size={h.get('size')})")
            return ([{"user": "System", "body": "\n".join(lines), "kind": "system"}], False)

        if cmd == "!stats" and args:
            w = get_world(" ".join(args))
            if not w or not _world_access(w, user):
                return ([{"user": "System", "body": "World not found or locked.", "kind": "system"}], False)
            return ([{"user": "System", "body": world_stats(w["id"]) or "World not found.", "kind": "system"}], False)

        if cmd == "!population":
            if args:
                w = get_world(" ".join(args))
                if not w or not _world_access(w, user):
                    return ([{"user": "System", "body": "World not found or locked.", "kind": "system"}], False)
                return ([{"user": "System", "body": world_population(w["id"]), "kind": "system"}], False)
            # all accessible
            worlds = [w for w in list_worlds() if _world_access(w, user)]
            total = 0
            rows = []
            for w in worlds:
                pop = w.get("population")
                try:
                    total += int(pop)
                except Exception:
                    pass
                rows.append(f"{w.get('id')} {w.get('name')}: {pop}")
            rows.append(f"TOTAL (numeric sum): {total}")
            return ([{"user": "System", "body": "\n".join(rows), "kind": "system"}], False)

        if cmd == "!map" and args:
            w = get_world(" ".join(args))
            if not w or not _world_access(w, user):
                return ([{"user": "System", "body": "World not found or locked.", "kind": "system"}], False)
            return ([{"user": "System", "body": ascii_map(w["id"]) or "(no map)", "kind": "system"}], False)

        if cmd == "!home" and len(args) >= 2 and args[0] in {"stats", "map"}:
            sub = args[0]
            hid = " ".join(args[1:])
            h = get_home(hid)
            if not h:
                return ([{"user": "System", "body": "Home not found.", "kind": "system"}], False)
            w = get_world(str(h.get("world", "")))
            if not w or not _world_access(w, user):
                return ([{"user": "System", "body": "Home belongs to a world you can't access.", "kind": "system"}], False)
            if sub == "stats":
                return ([{"user": "System", "body": home_stats(h["id"]) or "Home not found.", "kind": "system"}], False)
            return ([{"user": "System", "body": ascii_home(h["id"]) or "(no home map)", "kind": "system"}], False)

        if cmd == "!select" and len(args) >= 2 and args[0] == "world":
            w = get_world(" ".join(args[1:]))
            if not w or not _world_access(w, user):
                return ([{"user": "System", "body": "World not found or locked.", "kind": "system"}], False)
            self._profile_set(user, selected_world=w.get("id"))
            return ([{"user": "System", "body": f"Selected world set to {w.get('id')} — {w.get('name')}", "kind": "system"}], False)

        # Interactive create
        if cmd == "!create" and args:
            what = args[0].lower()
            if what == "world":
                # Optional: !create world beginner "Name"
                difficulty = "beginner"
                name_arg: Optional[str] = None
                if len(args) >= 2 and args[1].lower() in {"beginner", "medium", "advanced"}:
                    difficulty = args[1].lower()
                    if len(args) >= 3:
                        name_arg = " ".join(args[2:])
                elif len(args) >= 2:
                    name_arg = " ".join(args[1:])
                st = wizard_start("world", difficulty, name=name_arg)
                self._wizard[sid] = st
                q, _ = wizard_question(st)
                return ([{"user": "Builder", "body": f"World Builder started (difficulty: {difficulty}).\n" + q + "\n\nReply with 1-10. Type cancel to stop.", "kind": "system"}], False)

            if what == "home":
                # If user has selected world, prefill it; else ask with a system prompt.
                prof = self._profile_get(user)
                selected = prof.get("selected_world")
                st = wizard_start("home", "home", name=None)
                if selected:
                    st.answers["world"] = selected
                self._wizard[sid] = st
                if not selected:
                    return ([{"user": "Builder", "body": "Home Builder started. First, choose a world: type !select world <WID> (or !world list). Then run !create home again.", "kind": "system"}], False)
                q, _ = wizard_question(st)
                return ([{"user": "Builder", "body": "Home Builder started.\n" + q + "\n\nReply with 1-10. Type cancel to stop.", "kind": "system"}], False)

        # Manual create
        if cmd == "!world" and len(args) >= 1 and args[0] == "create":
            flags = _parse_kv_flags(args[1:])
            name = flags.get("name")
            if not name:
                return ([{"user": "System", "body": "Missing --name for world create.", "kind": "system"}], False)
            world = {
                "name": name,
                "biome": flags.get("biome", "forest"),
                "climate": flags.get("climate", "temperate"),
                "magic": flags.get("magic", "mid"),
                "tech": flags.get("tech", "low"),
                "governance": flags.get("governance", "council"),
                "economy": flags.get("economy", "trade"),
                "danger": flags.get("danger", "low"),
                "mood": flags.get("mood", "welcoming"),
                "population": int(flags.get("population", "1000")) if str(flags.get("population", "")).isdigit() else 1000,
                "owner": user,
                "visibility": flags.get("visibility", "public"),
                "allowed_users": [user],
                "tags": ["manual"],
            }
            created = create_world(world)
            state_changed = True
            return ([{"user": "System", "body": f"✅ World created: {created.get('id')} — {created.get('name')} (owner: {user})", "kind": "system"}], state_changed)

        if cmd == "!home" and len(args) >= 1 and args[0] == "create":
            flags = _parse_kv_flags(args[1:])
            name = flags.get("name")
            world_id = flags.get("world")
            if not name or not world_id:
                return ([{"user": "System", "body": "Missing --name or --world for home create.", "kind": "system"}], False)
            w = get_world(str(world_id))
            if not w or not _world_access(w, user):
                return ([{"user": "System", "body": "World not found or locked.", "kind": "system"}], False)
            home = {
                "name": name,
                "world": w.get("id"),
                "style": flags.get("style", "cottage"),
                "size": flags.get("size", "small"),
                "theme": flags.get("theme", "cozy"),
                "materials": flags.get("materials", "wood"),
                "security": flags.get("security", "low"),
                "amenities": flags.get("amenities", "garden"),
                "owner": user,
                "tags": ["manual"],
            }
            created = create_home(home)
            state_changed = True
            return ([{"user": "System", "body": f"✅ Home created: {created.get('id')} — {created.get('name')} (world: {created.get('world')})", "kind": "system"}], state_changed)

        # World locking / allow list
        if cmd == "!world" and len(args) >= 3 and args[0] == "lock":
            wid = args[1]
            mode = args[2].lower()
            w = get_world(wid)
            if not w:
                return ([{"user": "System", "body": "World not found.", "kind": "system"}], False)
            if str(w.get("owner", "")) != user:
                return ([{"user": "System", "body": "Only the owner can lock/unlock a world.", "kind": "system"}], False)
            if mode not in {"public", "private"}:
                return ([{"user": "System", "body": "Usage: !world lock <WID> public|private", "kind": "system"}], False)
            w["visibility"] = mode
            if mode == "private":
                allow = w.get("allowed_users") or []
                if user not in allow:
                    allow.append(user)
                w["allowed_users"] = allow
            # persist
            worlds = list_worlds()
            for i, ww in enumerate(worlds):
                if ww.get("id") == w.get("id"):
                    worlds[i] = w
                    break
            _save_json(WORLD_FILE, "worlds", worlds)
            state_changed = True
            return ([{"user": "System", "body": f"🔒 World {w.get('id')} set to {mode}.", "kind": "system"}], state_changed)

        if cmd == "!world" and len(args) >= 4 and args[0] == "allow":
            wid = args[1]
            action = args[2].lower()
            who = " ".join(args[3:])
            w = get_world(wid)
            if not w:
                return ([{"user": "System", "body": "World not found.", "kind": "system"}], False)
            if str(w.get("owner", "")) != user:
                return ([{"user": "System", "body": "Only the owner can change allow lists.", "kind": "system"}], False)
            allow = w.get("allowed_users") or []
            if not isinstance(allow, list):
                allow = []
            if action == "add":
                if who not in allow:
                    allow.append(who)
            elif action == "remove":
                if who in allow and who != user:
                    allow.remove(who)
            else:
                return ([{"user": "System", "body": "Usage: !world allow <WID> add|remove <username>", "kind": "system"}], False)
            w["allowed_users"] = allow
            worlds = list_worlds()
            for i, ww in enumerate(worlds):
                if ww.get("id") == w.get("id"):
                    worlds[i] = w
                    break
            _save_json(WORLD_FILE, "worlds", worlds)
            state_changed = True
            return ([{"user": "System", "body": f"✅ Allow list updated for {w.get('id')}: {', '.join(allow)}", "kind": "system"}], state_changed)

        return ([{"user": "System", "body": "Unknown command. Type !help", "kind": "system"}], False)


def parse_flags(text: str) -> Dict[str, Any]:
    # parse like: --name "X" --biome forest
    args = shlex.split(text)
    out: Dict[str, Any] = {}
    key = None
    for a in args:
        if a.startswith("--"):
            key = a[2:]
            out[key] = True
        else:
            if key is None:
                continue
            if out.get(key) is True:
                out[key] = a
            else:
                out[key] = str(out[key]) + " " + a
    return out


def format_world_list() -> str:
    worlds = list_worlds()
    if not worlds:
        return "No worlds yet. Try !create world"
    lines = ["Worlds:"]
    for w in worlds:
        lines.append(f"  {w.get('id','?')} — {w.get('name','(unnamed)')}  [biome={w.get('biome','?')}, magic={w.get('magic','?')}, pop={w.get('population','?')}]"
                    )
    return "\n".join(lines)


def format_home_list() -> str:
    homes = list_homes()
    if not homes:
        return "No homes yet. Try !create home"
    lines = ["Homes:"]
    for h in homes:
        lines.append(f"  {h.get('id','?')} — {h.get('name','(unnamed)')}  [world={h.get('world','?')}, style={h.get('style','?')}, size={h.get('size','?')}]"
                    )
    return "\n".join(lines)
