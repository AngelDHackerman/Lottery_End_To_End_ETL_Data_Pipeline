-- gold_5_de_oro_frequency — is every number of the 5 de Oro equally likely? (UY-032, UY-044.2)
--
-- Grain: (rules_version, ball_type, number). The range of numbers changed on 2014-03-19
-- (01-44 to 01-48, `game_rules`), so each range is tested apart: pooled, the four new numbers
-- would look rare. ball_type is `oro` (5 numbers), `extra` (1) or `revancha` (5).
--
-- Expected: every number of the range equally often, balls / N. Observed: its count; a number
-- that never came out is a row with 0. chi_square is Pearson's statistic with N - 1 degrees of
-- freedom. The k numbers of one draw are different (drawn without replacement), which makes
-- the counts vary less than independent draws would: chi_square_adjusted multiplies by
-- (N - 1) / (N - k) to undo it, and the verdicts use the adjusted value.
--
-- Excludes nothing: a number outside its range never reaches silver (it is quarantined).
WITH rules AS (
    SELECT
        value AS rules_version,
        valid_from,
        valid_to,
        CAST(substr(value, 4, 2) AS integer) AS range_size
    FROM silver_game_rules
    WHERE game = '5_de_oro' AND rule = 'rango_numeros'
),
balls AS (
    SELECT
        r.rules_version,
        r.valid_from,
        r.valid_to,
        r.range_size,
        n.ball_type,
        n.draw_date,
        CAST(n.number AS integer) AS number
    FROM silver_draw_numbers AS n
    INNER JOIN rules AS r
        ON n.draw_date >= r.valid_from
        AND (r.valid_to IS NULL OR n.draw_date <= r.valid_to)
    WHERE n.game = '5_de_oro'
),
groups AS (
    SELECT
        rules_version,
        valid_from,
        valid_to,
        range_size,
        ball_type,
        count(DISTINCT draw_date) AS draws,
        count(*) AS balls
    FROM balls
    GROUP BY rules_version, valid_from, valid_to, range_size, ball_type
),
counted AS (
    SELECT rules_version, ball_type, number, count(*) AS observed
    FROM balls
    GROUP BY rules_version, ball_type, number
),
all_numbers AS (
    SELECT number
    FROM (
        VALUES
        (1), (2), (3), (4), (5), (6), (7), (8), (9), (10), (11), (12),
        (13), (14), (15), (16), (17), (18), (19), (20), (21), (22), (23), (24),
        (25), (26), (27), (28), (29), (30), (31), (32), (33), (34), (35), (36),
        (37), (38), (39), (40), (41), (42), (43), (44), (45), (46), (47), (48)
    ) AS t (number)
),
cells AS (
    SELECT
        g.rules_version,
        g.valid_from,
        g.valid_to,
        g.range_size,
        g.ball_type,
        a.number,
        g.draws,
        g.balls,
        coalesce(c.observed, 0) AS observed,
        CAST(g.balls AS double) / g.range_size AS expected
    FROM groups AS g
    INNER JOIN all_numbers AS a ON a.number <= g.range_size
    LEFT JOIN counted AS c
        ON c.rules_version = g.rules_version
        AND c.ball_type = g.ball_type
        AND c.number = a.number
),
tested AS (
    SELECT
        cells.*,
        sum((observed - expected) * (observed - expected) / expected) OVER (
            PARTITION BY rules_version, ball_type
        ) AS chi_square,
        -- (N - 1) / (N - k), with k = balls per draw
        (range_size - 1) / (range_size - CAST(balls AS double) / draws) AS adjustment
    FROM cells
),
-- Upper critical values of the chi-square distribution (scipy.stats.chi2.ppf; a test
-- recomputes them). One row per range the game has had.
critical AS (
    SELECT
        degrees_of_freedom,
        CAST(critical_05 AS double) AS critical_05,
        CAST(critical_01 AS double) AS critical_01
    FROM (
        VALUES (43, 59.304, 67.459), (47, 64.001, 72.443)
    ) AS t (degrees_of_freedom, critical_05, critical_01)
)
SELECT
    '5_de_oro' AS game,
    t.rules_version,
    t.valid_from,
    t.valid_to,
    t.ball_type,
    lpad(CAST(t.number AS varchar), 2, '0') AS number,
    t.draws,
    t.observed,
    t.expected,
    t.chi_square,
    t.chi_square * t.adjustment AS chi_square_adjusted,
    t.range_size - 1 AS degrees_of_freedom,
    c.critical_05,
    c.critical_01,
    t.chi_square * t.adjustment > c.critical_05 AS rejects_05,
    t.chi_square * t.adjustment > c.critical_01 AS rejects_01
FROM tested AS t
LEFT JOIN critical AS c ON c.degrees_of_freedom = t.range_size - 1
ORDER BY t.valid_from, t.ball_type, t.number
