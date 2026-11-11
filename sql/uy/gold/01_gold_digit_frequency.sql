-- gold_digit_frequency — is every digit of the Quiniela equally likely? (UY-032, UY-044.2)
--
-- Grain: (game, scope, position, digit_place, digit). scope = 'total' pools the 20 positions
-- (position is null); scope = 'position' is one of the 20 places a number is drawn in (D3: in
-- the Quiniela the order is the draw order, and position 1 is "la cabeza").
--
-- Expected: each digit 0-9 in 1/10 of the numbers. Observed: its count. The test is Pearson's
-- chi-square with 9 degrees of freedom, repeated on every row of its group together with the
-- critical values, so a row can be read alone.
--
-- Reading it: this table runs 126 tests (2 games x 3 digit places x 21 scopes). At 5 % about
-- six of them reject by chance alone; one rejection is not evidence of a biased drum.
--
-- Excludes nothing: no dq_flag concerns a Quiniela number.
WITH numbers AS (
    SELECT game, position, number
    FROM silver_draw_numbers
    WHERE ball_type = 'quiniela'
),
digits AS (
    SELECT game, position, 'hundreds' AS digit_place, substr(number, 1, 1) AS digit FROM numbers
    UNION ALL
    SELECT game, position, 'tens' AS digit_place, substr(number, 2, 1) AS digit FROM numbers
    UNION ALL
    SELECT game, position, 'units' AS digit_place, substr(number, 3, 1) AS digit FROM numbers
),
-- position 0 stands for "every position" until the final SELECT turns it into null.
scoped AS (
    SELECT game, 'position' AS scope, position, digit_place, digit FROM digits
    UNION ALL
    SELECT game, 'total' AS scope, 0 AS position, digit_place, digit FROM digits
),
all_digits AS (
    SELECT digit
    FROM (VALUES ('0'), ('1'), ('2'), ('3'), ('4'), ('5'), ('6'), ('7'), ('8'), ('9')) AS t (digit)
),
groups AS (
    SELECT game, scope, position, digit_place, count(*) AS numbers
    FROM scoped
    GROUP BY game, scope, position, digit_place
),
counted AS (
    SELECT game, scope, position, digit_place, digit, count(*) AS observed
    FROM scoped
    GROUP BY game, scope, position, digit_place, digit
),
-- Every digit of every group, so a digit that never came out is a row with 0, not a hole.
cells AS (
    SELECT
        g.game,
        g.scope,
        g.position,
        g.digit_place,
        a.digit,
        g.numbers,
        coalesce(c.observed, 0) AS observed,
        CAST(g.numbers AS double) / 10 AS expected
    FROM groups AS g
    CROSS JOIN all_digits AS a
    LEFT JOIN counted AS c
        ON c.game = g.game
        AND c.scope = g.scope
        AND c.position = g.position
        AND c.digit_place = g.digit_place
        AND c.digit = a.digit
),
tested AS (
    SELECT
        cells.*,
        sum((observed - expected) * (observed - expected) / expected) OVER (
            PARTITION BY game, scope, position, digit_place
        ) AS chi_square
    FROM cells
),
-- Upper critical values of the chi-square distribution (scipy.stats.chi2.ppf; a test
-- recomputes them).
critical AS (
    SELECT
        degrees_of_freedom,
        CAST(critical_05 AS double) AS critical_05,
        CAST(critical_01 AS double) AS critical_01
    FROM (VALUES (9, 16.919, 21.666)) AS t (degrees_of_freedom, critical_05, critical_01)
)
SELECT
    t.game,
    t.scope,
    NULLIF(t.position, 0) AS position,
    t.digit_place,
    t.digit,
    t.numbers,
    t.observed,
    t.expected,
    CAST(t.observed AS double) / t.numbers AS observed_share,
    CAST(0.1 AS double) AS expected_share,
    t.chi_square,
    c.degrees_of_freedom,
    c.critical_05,
    c.critical_01,
    t.chi_square > c.critical_05 AS rejects_05,
    t.chi_square > c.critical_01 AS rejects_01
FROM tested AS t
CROSS JOIN critical AS c
ORDER BY t.game, t.scope DESC, t.position, t.digit_place, t.digit
