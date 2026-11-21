-- gold_quiniela_repeats — how often does a Quiniela draw repeat a number? (UY-032, UY-044.2)
--
-- Grain: (game, scope, year). scope = 'total' is the whole history (year is null);
-- scope = 'year' is one calendar year.
--
-- Expected: 20 independent draws from 000-999 repeat at least one number with probability
-- 1 - (999/1000)(998/1000)...(981/1000) = 17.41 % (the birthday problem; a test recomputes
-- it). Observed: the share of draws with a repeat. z_score is the distance between the two in
-- standard errors of a proportion; beyond +-1.96 is unusual at 5 %.
--
-- Excludes the draws that do not have exactly 20 Quiniela numbers, and counts them.
WITH per_draw AS (
    SELECT
        game,
        draw_date,
        count(*) AS balls,
        count(DISTINCT number) AS distinct_numbers
    FROM silver_draw_numbers
    WHERE ball_type = 'quiniela'
    GROUP BY game, draw_date
),
scoped AS (
    SELECT game, 'year' AS scope, CAST(year(draw_date) AS integer) AS year, balls, distinct_numbers FROM per_draw
    UNION ALL
    SELECT game, 'total' AS scope, 0 AS year, balls, distinct_numbers FROM per_draw
),
counted AS (
    SELECT
        game,
        scope,
        year,
        count_if(balls = 20) AS draws,
        count_if(balls <> 20) AS draws_excluded,
        count_if(balls = 20 AND distinct_numbers < 20) AS draws_with_repeat,
        CAST(0.1740715866407998 AS double) AS expected_rate
    FROM scoped
    GROUP BY game, scope, year
),
rated AS (
    SELECT
        counted.*,
        CAST(draws_with_repeat AS double) / NULLIF(draws, 0) AS observed_rate,
        sqrt(expected_rate * (1 - expected_rate) / NULLIF(draws, 0)) AS standard_error
    FROM counted
)
SELECT
    game,
    scope,
    NULLIF(year, 0) AS year,
    draws,
    draws_excluded,
    draws_with_repeat,
    observed_rate,
    expected_rate,
    standard_error,
    (observed_rate - expected_rate) / standard_error AS z_score
FROM rated
ORDER BY game, scope, year
