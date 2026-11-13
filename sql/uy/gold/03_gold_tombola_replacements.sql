-- gold_tombola_replacements — how many Tómbola numbers are replacements? (UY-032, UY-044.2)
--
-- The Tómbola is the last two digits of the 20 Quiniela numbers of the same draw; an ending
-- that repeats is replaced by another number (`is_replacement`), so the Tómbola has 20
-- different numbers.
--
-- Grain: (game, scope, year), as in gold_quiniela_repeats.
--
-- Expected: 20 independent endings from 00-99 cover 100 x (1 - 0.99^20) = 18.21 different
-- ones, so 1.79 replacements per draw. Observed: the mean of `is_replacement` per draw.
-- `implied_by_quiniela_mean` is the same count taken from the Quiniela numbers themselves
-- (20 minus their distinct endings): it must equal the observed mean, or the replacement
-- marks are wrong. z_score uses the sample's own deviation.
--
-- Excludes, and counts, the draws whose replacements are not known: flagged
-- `tombola_repeated_number` or `tombola_not_from_quiniela` (D22), or without a Tómbola.
WITH quiniela AS (
    SELECT
        game,
        draw_date,
        20 - count(DISTINCT substr(number, 2, 2)) AS implied_replacements
    FROM silver_draw_numbers
    WHERE ball_type = 'quiniela'
    GROUP BY game, draw_date
),
tombola AS (
    SELECT
        game,
        draw_date,
        count(*) AS balls,
        count_if(is_replacement) AS replacements,
        count_if(is_replacement IS NULL) AS unknown
    FROM silver_draw_numbers
    WHERE ball_type = 'tombola'
    GROUP BY game, draw_date
),
per_draw AS (
    SELECT
        d.game,
        d.draw_date,
        t.replacements,
        q.implied_replacements,
        (
            t.balls IS NULL
            OR t.balls <> 20
            OR t.unknown > 0
            OR contains(d.dq_flags, 'tombola_repeated_number')
            OR contains(d.dq_flags, 'tombola_not_from_quiniela')
        ) AS excluded
    FROM silver_draws AS d
    INNER JOIN quiniela AS q ON q.game = d.game AND q.draw_date = d.draw_date
    LEFT JOIN tombola AS t ON t.game = d.game AND t.draw_date = d.draw_date
),
scoped AS (
    SELECT game, 'year' AS scope, CAST(year(draw_date) AS integer) AS year, replacements, implied_replacements, excluded
    FROM per_draw
    UNION ALL
    SELECT game, 'total' AS scope, 0 AS year, replacements, implied_replacements, excluded
    FROM per_draw
),
measured AS (
    SELECT
        game,
        scope,
        year,
        count_if(NOT excluded) AS draws,
        count_if(excluded) AS draws_excluded,
        sum(replacements) FILTER (WHERE NOT excluded) AS replacements,
        avg(CAST(replacements AS double)) FILTER (WHERE NOT excluded) AS observed_mean,
        avg(CAST(implied_replacements AS double)) FILTER (WHERE NOT excluded) AS implied_by_quiniela_mean,
        stddev_samp(CAST(replacements AS double)) FILTER (WHERE NOT excluded) AS deviation
    FROM scoped
    GROUP BY game, scope, year
),
rated AS (
    SELECT
        measured.*,
        20 - 100 * (1 - power(CAST(0.99 AS double), 20)) AS expected_mean,
        deviation / sqrt(NULLIF(draws, 0)) AS standard_error
    FROM measured
)
SELECT
    game,
    scope,
    NULLIF(year, 0) AS year,
    draws,
    draws_excluded,
    replacements,
    observed_mean,
    expected_mean,
    implied_by_quiniela_mean,
    standard_error,
    (observed_mean - expected_mean) / NULLIF(standard_error, 0) AS z_score
FROM rated
ORDER BY game, scope, year
