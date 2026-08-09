# Sorteo fixtures

Three real files captured from `s3://lottery-partitioned-storage-prod/raw/`, **with the
vendor names scrubbed**. They are the input to `tests/unit/test_parser.py` and
`tests/unit/test_transformer.py`.

| File | Sorteo | Year | Premios | `NO VENDIDO` | Why this one |
|---|---|---|---|---|---|
| `ordinario_3046.txt` | 3046 ordinario | 2024 | 875 | 19 | the baseline "normal file" |
| `ordinario_3132.txt` | 3132 ordinario | 2026 | 895 | 10 | most recent capture — catches format drift since 2024 |
| `extraordinario_413.txt` | 413 extraordinario | 2026 | 1984 | **0** | different `tipo_sorteo`, its own numbering series, and no unsold prizes |

The extraordinario earns its place twice over: extraordinarios are numbered in a **separate
sequence** (411, 412, 413 — not the 3xxx ordinario series), so anything that assumes
`numero_sorteo > 3000` breaks on it; and it contains **zero** `NO VENDIDO` lines, so any code
that assumes unsold prizes always exist breaks too.

## Anonymization

The raw files name the person who sold each winning ticket:

```
VENDIDO POR JUAN TOMAS TIQUIRAM, DE SAN LUCAS SACATEPÉQUEZ, SACATEPÉQUEZ
```

The S3 bucket is private. **This directory is not** — it is committed to a public GitHub
repo. So the name is replaced, and only the name:

```
VENDIDO POR VENDOR_001, DE SAN LUCAS SACATEPÉQUEZ, SACATEPÉQUEZ
```

**Only the name segment changes.** `vendido_por` is comma-delimited and
`parser.split_vendido_por_column` splits on commas, so collapsing the whole field to a bare
`VENDOR_001` would erase ciudad and departamento — and with them the ability to test that
function at all, including its ciudad-only branch (143 of the 261 seller lines here have no
departamento, because `DE ESTA CAPITAL` carries no second comma). Ciudad and departamento
are public geography, not personal data, and they stay verbatim.

`NO VENDIDO` lines are untouched: that is a parser branch, not a person.

165 distinct names were replaced across the three files, with a **stable map** — the same
person is the same `VENDOR_NNN` in every file.

> **Note on what else was in that field.** The name segment sometimes carries more than a
> name. Real example from the capture: `PERSONA CON DISCAPACIDAD VISUAL <nombre>`. Replacing
> the whole segment — rather than trying to match name-shaped substrings — is what makes that
> disappear too. It is also a reminder that `raw/` and `silver_premios_premios.vendedor` hold
> more sensitive data than "vendor names" suggests.

## Regenerating

Do it in **one** invocation — the shared name map is what keeps the ids consistent across
files:

```bash
aws s3 cp s3://lottery-partitioned-storage-prod/raw/year=.../<file>.txt /tmp/raw/ordinario_3046.txt
python scripts/anonymize_fixture.py --out-dir tests/fixtures/sorteos /tmp/raw/*.txt
```

Then re-run the guard and update the `EXPECTED` table in `tests/unit/test_parser.py` if the
counts moved:

```bash
python scripts/anonymize_fixture.py --check tests/fixtures/sorteos/*.txt
```

`--check` exits non-zero if any `VENDIDO POR` line holds something that is not a
`VENDOR_NNN` placeholder. Run it before committing a regenerated fixture.
