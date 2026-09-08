"""Pure helpers for normalizing exercise names (GYM-27).

Used to de-duplicate the ``exercises`` catalog: "Жим лежачи", "жим лежачи "
(trailing space, different case), and "Жим лежачи’" (curly apostrophe)
should all resolve to the same catalog row instead of three near-duplicate
ones — the same kind of "same thing, typed differently" problem that
already exists in ``workout_sets.exercise_name`` (free text from the bot
FSM and Google Sheets, never previously de-duplicated).
"""

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_exercise_name(name: str) -> str:
    """Canonical form of an exercise name for catalog de-duplication.

    - Trims leading/trailing whitespace and collapses any run of internal
      whitespace to a single space.
    - Unifies the curly apostrophe (’, U+2019) to the straight one (', a
      common substitution some keyboards/autocorrect make) so a name typed
      either way maps to the same entry.
    - Lowercases, for case-insensitive matching.

    Deliberately narrow: this catches "same name, typed differently", not
    fuzzy/near-duplicate matching (accents, transliteration, synonyms are
    out of scope) — a normalized collision should always mean "this is
    genuinely the same exercise", never a false positive.
    """
    collapsed = _WHITESPACE_RE.sub(" ", name.strip())
    return collapsed.replace("’", "'").lower()
