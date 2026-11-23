"""Strict loader for a country's configuration (docs/uruguay/DESIGN.md, D4 and P4).

A country folder holds ``site.yaml``, one ``games/<game>.yaml`` per game and
``reference/game_rules.csv``. The YAML is configuration, not data: it never reaches bronze
or silver. It is read once at start-up and everything wrong with it fails there, in CI,
and never halfway through a run:

- ``yaml.safe_load`` semantics, plus **duplicate keys are an error** (plain safe_load keeps
  the last one without a word);
- a key the schema does not know is an error, and so is a missing one;
- text must be a YAML string. The repo's files quote every text, so ``no`` (Norway) never
  arrives as ``False`` nor ``2006-08-11`` as a ``date``;
- cross-references are checked: every ``range_rule`` exists in ``game_rules.csv`` for its
  game, every ``replacements_from`` and ``not_in`` names a ball type of the same game, a
  source without ``kind`` names a page of ``site.yaml``, and the parser epochs of a source
  neither overlap nor leave a gap.

Validated with plain dataclasses on purpose (P4): pydantic would add a compiled binary to
the Lambda package to check four files.

URL templates (``path`` and ``params``) may use ``{day}``, ``{month}`` and ``{year}`` as
integers, with a format spec when the site wants padding (``{day:02d}``).
"""

from __future__ import annotations

import csv
import re
import string
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MONEY_STYLES = ("us", "uy")
SOURCE_KINDS = ("extracto_php", "extracto_pdf", "pozos_pdf")
SOURCE_ROLES = ("primary", "timing", "cross_check", "backup", "draw_number")
ORDERS = ("drawn", "sorted")
TEMPLATE_FIELDS = frozenset({"day", "month", "year"})

_NAME = r"[a-z0-9_]+"


class ConfigError(ValueError):
    """A configuration file does not match the schema. The message says where."""


# --- YAML: safe_load, minus silent duplicate keys -------------------------------------------


class _StrictLoader(yaml.SafeLoader):
    pass


def _mapping_without_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ConfigError(f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates
)


def read_yaml(path: Path) -> object:
    try:
        with open(path, encoding="utf-8") as fh:
            # A SafeLoader subclass that only adds the duplicate-key check.
            return yaml.load(fh, Loader=_StrictLoader)  # nosec B506
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name}: not valid YAML: {exc}") from exc
    except ConfigError as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc


# --- Reading one mapping, key by key ----------------------------------------------------------


class _Fields:
    """One YAML mapping, consumed key by key. Whatever is left at :meth:`done` is unknown."""

    def __init__(self, raw: object, where: str) -> None:
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: expected a mapping, got {type(raw).__name__}")
        for key in raw:
            if not isinstance(key, str):
                raise ConfigError(f"{where}: keys must be text, got {key!r}")
        self._raw = dict(raw)
        self.where = where

    def has(self, key: str) -> bool:
        return key in self._raw

    def _take(self, key: str, required: bool) -> object:
        if key not in self._raw:
            if required:
                raise ConfigError(f"{self.where}: missing '{key}'")
            return None
        return self._raw.pop(key)

    def text(self, key, *, required=True, choices=None, pattern=None) -> str | None:
        value = self._take(key, required)
        if value is None and not required:
            return None
        return _text(value, f"{self.where}.{key}", choices=choices, pattern=pattern)

    def integer(self, key, *, minimum=1) -> int:
        value = self._take(key, required=True)
        # bool is an int in Python; `count: yes` is a mistake, not a 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{self.where}.{key}: expected an integer, got {value!r}")
        if value < minimum:
            raise ConfigError(f"{self.where}.{key}: must be >= {minimum}, got {value}")
        return value

    def boolean(self, key, *, required=True) -> bool | None:
        value = self._take(key, required)
        if value is None and not required:
            return None
        if not isinstance(value, bool):
            raise ConfigError(f"{self.where}.{key}: expected true or false, got {value!r}")
        return value

    def day(self, key, *, required=True) -> date | None:
        value = self.text(key, required=required, pattern=r"\d{4}-\d{2}-\d{2}")
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(f"{self.where}.{key}: not a date: {value!r}") from exc

    def texts(self, key, *, required=True, choices=None) -> tuple[str, ...]:
        value = self._take(key, required)
        if value is None and not required:
            return ()
        if not isinstance(value, list) or not value:
            raise ConfigError(f"{self.where}.{key}: expected a non-empty list")
        items = tuple(
            _text(v, f"{self.where}.{key}[{i}]", choices=choices) for i, v in enumerate(value)
        )
        if len(set(items)) != len(items):
            raise ConfigError(f"{self.where}.{key}: repeated values {list(items)}")
        return items

    def mapping(self, key, *, required=True) -> dict:
        value = self._take(key, required)
        if value is None and not required:
            return {}
        if not isinstance(value, dict) or not value:
            raise ConfigError(f"{self.where}.{key}: expected a non-empty mapping")
        return value

    def items(self, key, *, required=True) -> list:
        value = self._take(key, required)
        if value is None and not required:
            return []
        if not isinstance(value, list) or not value:
            raise ConfigError(f"{self.where}.{key}: expected a non-empty list")
        return value

    def done(self) -> None:
        if self._raw:
            raise ConfigError(f"{self.where}: unknown key(s) {sorted(self._raw)}")


def _text(value, where, *, choices=None, pattern=None) -> str:
    if not isinstance(value, str):
        raise ConfigError(
            f"{where}: expected a quoted string, got {type(value).__name__} {value!r}"
        )
    if not value.strip():
        raise ConfigError(f"{where}: empty")
    if choices is not None and value not in choices:
        raise ConfigError(f"{where}: {value!r} is not one of {list(choices)}")
    if pattern is not None and not re.fullmatch(pattern, value):
        raise ConfigError(f"{where}: {value!r} does not match {pattern}")
    return value


def _template(value: str, where: str) -> str:
    """Check a URL template uses only {day}, {month} and {year}, and that it renders."""
    try:
        fields = {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}
        if not fields <= TEMPLATE_FIELDS:
            raise ConfigError(f"{where}: unknown placeholder(s) {sorted(fields - TEMPLATE_FIELDS)}")
        value.format(day=1, month=1, year=2000)
    except (ValueError, IndexError, KeyError) as exc:
        raise ConfigError(f"{where}: not a usable template {value!r}: {exc}") from exc
    return value


# --- The schema -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Epoch:
    version: int
    valid_from: date
    valid_to: date | None


@dataclass(frozen=True)
class Page:
    """A site-wide page with every game of the day (``site.yaml``, ``pages``)."""

    name: str
    path: str
    params: dict[str, str]
    money_style: str | None
    parser_epochs: tuple[Epoch, ...]


@dataclass(frozen=True)
class SourceSpec:
    """One source of a game. Without ``kind`` it is a reference to a page of the site."""

    name: str
    role: str
    kind: str | None
    path: str | None
    params: dict[str, str]
    valid_from: date | None
    money_style: str | None
    parser_epochs: tuple[Epoch, ...]


@dataclass(frozen=True)
class Numbers:
    """The shape of one ``ball_type`` of a draw (DESIGN.md, D3)."""

    ball_type: str
    count: int
    digits: int
    order: str | None
    repeats: bool | None
    range_rule: str | None
    replacements_from: str | None
    not_in: tuple[str, ...]


@dataclass(frozen=True)
class Calendar:
    weekdays: tuple[str, ...]
    next_draw_label: str
    publish_after_local: time


@dataclass(frozen=True)
class Game:
    game: str
    name: str
    site_code: int
    calendar: Calendar
    sources: tuple[SourceSpec, ...]
    numbers: dict[str, Numbers]
    prizes: tuple[str, ...]


@dataclass(frozen=True)
class Site:
    country: str
    operator: str
    operator_name: str
    base_url: str
    timezone: str
    currency: str
    history_starts: date
    pages: dict[str, Page]
    other_games: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class Country:
    site: Site
    games: dict[str, Game]
    rules: frozenset[tuple[str, str]]  # (game, rule) pairs of game_rules.csv


def _epochs(raw: list, where: str) -> tuple[Epoch, ...]:
    epochs = []
    for i, item in enumerate(raw):
        f = _Fields(item, f"{where}[{i}]")
        epoch = Epoch(f.integer("version"), f.day("valid_from"), f.day("valid_to", required=False))
        f.done()
        if epoch.valid_to is not None and epoch.valid_to < epoch.valid_from:
            raise ConfigError(f"{where}[{i}]: valid_to is before valid_from")
        epochs.append(epoch)
    for prev, nxt in zip(epochs, epochs[1:], strict=False):
        if nxt.version <= prev.version or nxt.valid_from <= prev.valid_from:
            raise ConfigError(f"{where}: epochs must go forward in version and in valid_from")
        # Closed by the next one: an explicit valid_to has to meet it exactly.
        if prev.valid_to is not None and prev.valid_to != nxt.valid_from - timedelta(days=1):
            raise ConfigError(
                f"{where}: epoch {prev.version} ends {prev.valid_to} but {nxt.version} starts "
                f"{nxt.valid_from} — epochs may neither overlap nor leave a gap"
            )
    return tuple(epochs)


def _params(raw: dict, where: str) -> dict[str, str]:
    _Fields(raw, where)  # the keys are query parameter names, so they must be text
    return {k: _template(_text(v, f"{where}.{k}"), f"{where}.{k}") for k, v in raw.items()}


def _page(name: str, raw: object) -> Page:
    where = f"site.pages.{name}"
    f = _Fields(raw, where)
    page = Page(
        name=name,
        path=_template(f.text("path", pattern=r"/\S*"), f"{where}.path"),
        params=_params(f.mapping("params", required=False), f"{where}.params"),
        money_style=f.text("money_style", required=False, choices=MONEY_STYLES),
        parser_epochs=_epochs(f.items("parser_epochs"), f"{where}.parser_epochs"),
    )
    f.done()
    return page


def _codes(raw: object, where: str) -> tuple[int, ...]:
    """``[1, "6-18"]`` -> (1, 6, 7, ..., 18). A range is a quoted ``"a-b"``."""
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{where}: expected a non-empty list of codes")
    codes: list[int] = []
    for item in raw:
        if isinstance(item, int) and not isinstance(item, bool):
            codes.append(item)
        elif isinstance(item, str) and (m := re.fullmatch(r"(\d+)-(\d+)", item)):
            low, high = int(m[1]), int(m[2])
            if low >= high:
                raise ConfigError(f"{where}: empty range {item!r}")
            codes.extend(range(low, high + 1))
        else:
            raise ConfigError(f'{where}: {item!r} is neither a code nor a "low-high" range')
    if len(set(codes)) != len(codes):
        raise ConfigError(f"{where}: a code is listed twice")
    return tuple(codes)


def load_site(path: Path) -> Site:
    where = path.name
    f = _Fields(read_yaml(path), where)
    timezone = f.text("timezone")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"{where}.timezone: unknown time zone {timezone!r}") from exc
    pages = f.mapping("pages")
    other_games = f.mapping("other_games", required=False)
    site = Site(
        country=f.text("country", pattern=r"[a-z]{2}"),
        operator=f.text("operator", pattern=_NAME),
        operator_name=f.text("operator_name"),
        base_url=f.text("base_url", pattern=r"https://[^/\s]+"),
        timezone=timezone,
        currency=f.text("currency", pattern=r"[A-Z]{3}"),
        history_starts=f.day("history_starts"),
        pages={
            _text(name, f"{where}.pages", pattern=_NAME): _page(name, raw)
            for name, raw in pages.items()
        },
        other_games={
            _text(game, f"{where}.other_games", pattern=_NAME): _codes(
                codes, f"{where}.other_games.{game}"
            )
            for game, codes in other_games.items()
        },
    )
    f.done()
    return site


def _source(raw: object, where: str, site: Site) -> SourceSpec:
    f = _Fields(raw, where)
    name = f.text("name", pattern=_NAME)
    role = f.text("role", choices=SOURCE_ROLES)
    kind = f.text("kind", required=False, choices=SOURCE_KINDS)
    if kind is None:
        # A reference to a site page: the page carries its own path, params and epochs.
        f.done()
        if name not in site.pages:
            raise ConfigError(f"{where}: no kind, and {name!r} is not a page of site.yaml")
        return SourceSpec(name, role, None, None, {}, None, None, ())
    if kind == "pozos_pdf":
        # Its folder mixes date formats, so the URL is the results page's own link (UY-001).
        if f.has("path"):
            raise ConfigError(f"{where}: a pozos_pdf URL comes from the results page, no path")
        path = None
    else:
        path = f.text("path", pattern=r"/\S*")
    spec = SourceSpec(
        name=name,
        role=role,
        kind=kind,
        path=None if path is None else _template(path, f"{where}.path"),
        params=_params(f.mapping("params", required=False), f"{where}.params"),
        valid_from=f.day("valid_from", required=kind == "extracto_pdf"),
        money_style=f.text("money_style", required=False, choices=MONEY_STYLES),
        parser_epochs=_epochs(
            f.items("parser_epochs", required=kind == "extracto_php"), f"{where}.parser_epochs"
        ),
    )
    f.done()
    if kind == "extracto_pdf" and spec.parser_epochs:
        # Backup only: silver always comes from the HTML (owner, UY-003).
        raise ConfigError(f"{where}: an extracto_pdf is never parsed, so it has no parser_epochs")
    return spec


def _numbers(ball_type: str, raw: object, where: str) -> Numbers:
    f = _Fields(raw, where)
    numbers = Numbers(
        ball_type=ball_type,
        count=f.integer("count"),
        digits=f.integer("digits"),
        order=f.text("order", required=False, choices=ORDERS),
        repeats=f.boolean("repeats", required=False),
        range_rule=f.text("range_rule", required=False, pattern=_NAME),
        replacements_from=f.text("replacements_from", required=False, pattern=_NAME),
        not_in=f.texts("not_in", required=False),
    )
    f.done()
    return numbers


def load_game(path: Path, site: Site, rules: frozenset[tuple[str, str]]) -> Game:
    where = f"games/{path.name}"
    f = _Fields(read_yaml(path), where)
    game_name = f.text("game", pattern=_NAME)
    if game_name != path.stem:
        raise ConfigError(f"{where}: game {game_name!r} does not match the file name")
    cal = _Fields(f.mapping("calendar"), f"{where}.calendar")
    publish = cal.text("publish_after_local", pattern=r"([01]\d|2[0-3]):[0-5]\d")
    calendar = Calendar(
        weekdays=cal.texts("weekdays", choices=WEEKDAYS),
        next_draw_label=cal.text("next_draw_label"),
        publish_after_local=time.fromisoformat(publish),
    )
    cal.done()
    sources = tuple(
        _source(raw, f"{where}.sources[{i}]", site) for i, raw in enumerate(f.items("sources"))
    )
    numbers = {
        _text(ball_type, f"{where}.numbers", pattern=_NAME): _numbers(
            ball_type, raw, f"{where}.numbers.{ball_type}"
        )
        for ball_type, raw in f.mapping("numbers").items()
    }
    game = Game(
        game=game_name,
        name=f.text("name"),
        site_code=f.integer("site_code"),
        calendar=calendar,
        sources=sources,
        numbers=numbers,
        prizes=f.texts("prizes", required=False),
    )
    f.done()

    names = [s.name for s in sources]
    if len(set(names)) != len(names):
        raise ConfigError(f"{where}.sources: a source name is repeated")
    for spec in numbers.values():
        at = f"{where}.numbers.{spec.ball_type}"
        for other in (*((spec.replacements_from,) if spec.replacements_from else ()), *spec.not_in):
            if other not in numbers or other == spec.ball_type:
                raise ConfigError(f"{at}: {other!r} is not another ball type of this game")
        if spec.range_rule and (game_name, spec.range_rule) not in rules:
            raise ConfigError(f"{at}: range_rule {spec.range_rule!r} is not in game_rules.csv")
    return game


def load_rules(path: Path) -> frozenset[tuple[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not {"game", "rule"} <= set(reader.fieldnames or ()):
            raise ConfigError(f"{path.name}: needs 'game' and 'rule' columns")
        return frozenset((row["game"], row["rule"]) for row in reader)


def load_country(directory: Path) -> Country:
    """Load and cross-check ``site.yaml``, ``games/*.yaml`` and ``reference/game_rules.csv``."""
    directory = Path(directory)
    site = load_site(directory / "site.yaml")
    rules = load_rules(directory / "reference" / "game_rules.csv")
    games = {
        p.stem: load_game(p, site, rules) for p in sorted((directory / "games").glob("*.yaml"))
    }
    if not games:
        raise ConfigError(f"{directory}: no games/*.yaml")

    codes: dict[int, str] = {}
    for name, game_codes in [
        *((g.game, (g.site_code,)) for g in games.values()),
        *site.other_games.items(),
    ]:
        if name in games and name in site.other_games:
            raise ConfigError(f"{name!r} is both a game file and an entry of other_games")
        for code in game_codes:
            if code in codes:
                raise ConfigError(f"site code {code} belongs to both {codes[code]!r} and {name!r}")
            codes[code] = name

    owner: dict[str, str] = {}
    for game in games.values():
        for spec in game.sources:
            if spec.kind is not None and spec.name in owner:
                raise ConfigError(
                    f"source {spec.name!r} is declared by {owner[spec.name]!r} and {game.game!r}"
                )
            owner[spec.name] = game.game
    return Country(site=site, games=games, rules=rules)
