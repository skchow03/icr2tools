"""
SG CREATE marquee message bank.

Use MARQUEE_MESSAGES for a flat randomized ticker pool, or use
MARQUEE_MESSAGE_CATEGORIES if the UI later wants category filters.
Messages are intentionally mild, corny, and fictional.
"""

from __future__ import annotations

from random import choice


GENERAL_CREW_MESSAGES: list[str] = [
    "The survey team has confirmed the track is mostly where we left it.",
    "Construction crew reports all cones are probably temporary.",
    "One intern has been assigned to stare at DLONG values until morale improves.",
    "Pavement crew requests fewer surprise hairpins before lunch.",
    "Track design team has moved one apex three feet and declared victory.",
    "Grandstand committee says every seat has a theoretical view.",
    "Safety inspector asks why Turn 4 looks like that.",
    "Local zoning board approves track, provided it remains fictional.",
    "A construction worker has found an old apex buried under the infield.",
    "Crew chief says the layout is bold, which may or may not be a compliment.",
    "The earthworks team has misplaced a hill but expects to find it soon.",
    "Workers are currently arguing whether this is a chicane or a lifestyle choice.",
    "Maintenance reports the start/finish line is still starting and finishing.",
    "The paving machine has requested a straighter straight.",
    "All corners have been reminded to face the correct direction.",
    "The bridge crew says the bridge will be installed as soon as anyone asks for one.",
    "The design office has filed a memo titled: Maybe Less Wall?",
    "Trackside shrubs have been placed for realism and plausible deniability.",
    "The tire barrier budget has been moved to future enthusiasm.",
    "Several workers are pretending to understand banking.",
    "The project manager says the track is 87% more official with labels.",
    "Snack truck delayed by unexpected f-section complexity.",
    "One marshal has been assigned to each confusing decision.",
    "The blueprint printer is out of cyan, so grass may be approximate.",
    "A cone has been promoted to senior traffic consultant.",
    "The runoff area has run off.",
    "The crew measured twice and clicked once.",
    "The pit lane has asked to be included in future planning.",
    "The infield pond is not a pond. It is an unresolved terrain feature.",
    "The construction office denies all knowledge of Turn 7.",
]

DESIGN_OFFICE_MESSAGES: list[str] = [
    "Design memo: every great circuit needs one corner nobody can explain.",
    "Engineering note: radius is signed because the curve has opinions.",
    "The geometry department has requested coffee and fewer disconnected endpoints.",
    "Apex committee meeting postponed due to lack of consensus.",
    "The chief designer has approved the latest layout with a suspicious squint.",
    "The elevation team says flat is a valid artistic direction.",
    "Camber review complete: everyone nodded at the graph.",
    "Track geometry is currently within acceptable levels of drama.",
    "DLONG alignment committee recommends not touching anything for five minutes.",
    "The design team has renamed a mistake character.",
    "The new section passed review after being rotated until it looked intentional.",
    "The circuit now has flow, assuming sufficient imagination.",
    "Memo from engineering: if it closes, it counts.",
    "The inspector says the track is technically continuous, emotionally uncertain.",
    "Drafting department reports that the back straight has become a back suggestion.",
    "Corner naming rights available for turns that survive export.",
    "The layout has been optimized for bravery, confusion, and moderate frame rate.",
    "A senior designer has described the circuit as period-correct weird.",
    "Wind tunnel unavailable; cones were used instead.",
    "The committee recommends adding one more sweeping bend, then immediately regrets it.",
]

CONSTRUCTION_MESSAGES: list[str] = [
    "Crew update: asphalt is hot, tempers are medium, geometry is variable.",
    "Bulldozer operator asks whether the track is supposed to loop back.",
    "Survey stakes have unionized.",
    "A paving crew member has described the new corner as spicy but legal.",
    "Construction paused while everyone watches the preview zoom animation.",
    "The crane operator refuses to move until the object list makes sense.",
    "Flag stand installed. Flag not included.",
    "Workers found an old racing line and are keeping it as a pet.",
    "Lunch break extended due to excessive curvature.",
    "Concrete crew requests wall heights in numbers, not vibes.",
    "A foreman has labeled the runoff good enough for testing.",
    "The crew has swept the racing line into a neat pile.",
    "Pit wall installation delayed by philosophical disagreement over left and right.",
    "Someone parked the steamroller on the apex again.",
    "Guardrail delivery arrived, but only for the easy corners.",
    "Construction note: do not ask why the fence crosses the grass.",
    "The pavers followed the centerline. Mostly.",
    "Crew morale improves whenever the track closes properly.",
    "All workers have been instructed not to lean on the control points.",
    "Temporary barriers are now permanent until further notice.",
]

ICR2_FLAVORED_MESSAGES: list[str] = [
    "Papyrus-era officials confirm this is exactly as precise as 1995 intended.",
    "DOSBox weather forecast: partly pixelated, chance of palette issues.",
    "Legacy renderer requests fewer triangles and more optimism.",
    "The track file says everything is fine. The preview has follow-up questions.",
    "ICR2 officials have approved the circuit after checking one byte.",
    "DAT packing crew reports the box is full but the lid still closes.",
    "The 3D crew has hidden several objects where only modders will find them.",
    "LP department says the AI drivers are learning, slowly.",
    "Camera crew asks why the best shot is always behind a wall.",
    "Texture department has used 16 colors and a dream.",
    "Sunny.PCX has entered the chat.",
    "The replay cameras have been placed by a committee of squirrels.",
    "TSO placement verified by standing far away from the monitor.",
    "The wall file has been asked to stop making eye contact.",
    "The MRK team has added skid marks where the testers screamed.",
]

INTEGRITY_CHECK_MESSAGES: list[str] = [
    "Integrity check says the track has only minor existential concerns.",
    "No major problems found, except the ones with personality.",
    "Inspector reports: It loads is not a full compliance standard.",
    "Geometry health: stable enough to continue pretending.",
    "The validation team has discovered a corner with ambition.",
    "Track passed inspection after the inspector zoomed out.",
    "Warning: this section may contain traces of previous decisions.",
    "Export department says the track is legal in at least three dimensions.",
    "Everything is connected, except the project timeline.",
    "The loop is closed. The case remains open.",
    "The surface mesh has concerns but is willing to cooperate.",
    "Current build status: cautiously drivable.",
    "The preview has refreshed and would like recognition.",
]

DESIGNER_MEMO_MESSAGES: list[str] = [
    "Memo from Johan Hugenhaltz: A corner should surprise the driver, but not the file parser.",
    "Memo from Herman Tinkerer: If the apex is wrong, simply redefine success.",
    "Memo from Toby Curbman: More curbs. Not everywhere. But also maybe everywhere.",
    "Johan Hugenhaltz recommends one elegant bend and one deeply suspicious bend.",
    "Herman Tinkerer has approved the pit exit with only minor eyebrow movement.",
    "Toby Curbman says the runoff is emotionally sufficient.",
    "Johan Hugenhaltz asks whether the straight is too straight.",
    "Herman Tinkerer has rotated the whole track and called it urban planning.",
    "Toby Curbman requests additional curb budget and fewer questions.",
    "Design memo: Hugenhaltz likes the flow, Tinkerer likes the math, Curbman likes the curbs.",
]

SHORT_TICKER_MESSAGES: list[str] = [
    "Survey crew reports: close enough.",
    "Paving in progress. Please admire responsibly.",
    "Apex relocated due to vibes.",
    "The cone department is thriving.",
    "Track morale: acceptable.",
    "Guardrails are thinking about it.",
    "Runoff added where fear was detected.",
    "Pit lane still negotiating.",
    "Curve radius has entered witness protection.",
    "DLONGs continue to be long.",
    "FSECTs are behaving today.",
    "TSOs are standing by.",
    "TSD crew claims they were here earlier.",
    "Elevation team found another bump.",
    "Camber department says maybe.",
    "Export crew holding its breath.",
    "Preview refreshed. Nothing exploded.",
    "Track closed. Emotionally open.",
    "Grass installed by committee.",
    "Wall crew recommends caution.",
    "Start line starts. Finish line finishes.",
    "Object list doing object things.",
    "Palette optimism rising.",
    "Apex confidence: medium.",
    "Construction noise simulated.",
    "The back straight has opinions.",
    "More curbs under review.",
    "Less wall under discussion.",
    "The marshal hut is decorative, probably.",
    "One fence refuses to align.",
    "Design team says ship it cautiously.",
]

MARQUEE_MESSAGE_CATEGORIES: dict[str, list[str]] = {
    "general_crew": GENERAL_CREW_MESSAGES,
    "design_office": DESIGN_OFFICE_MESSAGES,
    "construction": CONSTRUCTION_MESSAGES,
    "icr2_flavored": ICR2_FLAVORED_MESSAGES,
    "integrity_check": INTEGRITY_CHECK_MESSAGES,
    "designer_memos": DESIGNER_MEMO_MESSAGES,
    "short_ticker": SHORT_TICKER_MESSAGES,
}

MARQUEE_MESSAGES: list[str] = [
    message
    for category_messages in MARQUEE_MESSAGE_CATEGORIES.values()
    for message in category_messages
]


def random_marquee_message(category: str | None = None) -> str:
    """Return one random marquee message.

    Args:
        category: Optional key from MARQUEE_MESSAGE_CATEGORIES.

    Raises:
        KeyError: If category is provided but not known.
    """
    if category is None:
        return choice(MARQUEE_MESSAGES)

    return choice(MARQUEE_MESSAGE_CATEGORIES[category])
