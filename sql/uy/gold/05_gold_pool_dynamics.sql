-- gold_pool_dynamics — does a pool grow until someone wins it? (UY-032, UY-044.2)
--
-- Grain: (draw_date, prize), one row per 5 de Oro pool as published: `oro`, `plata`,
-- `revancha`. Amounts are nominal pesos (D6): nothing here adjusts for inflation.
--
-- Expected: a pool nobody won carries over, so the next one is higher (`up`); a pool that was
-- won starts again, so the next one is lower (`down`). Observed: what the next published pool
-- did. `as_expected` compares the two, and is null when the previous draw's winners are not
-- known. The expectation is a hypothesis about each pool, not a rule of the game: the share
-- of rows where it holds, per prize, is the finding.
--
-- Excludes from the comparison, without dropping them: such a row stays in the table with
-- `excluded_reason` and nulls, and the row after it is compared with the last usable one.
-- Reasons: `pozo_plata_equals_oro` or
-- `amount_sources_differ` (dq_flags, D22), or `no_amount` (the cell was empty: null, never 0).
WITH prizes AS (
    SELECT
        game,
        draw_date,
        prize,
        pool_amount,
        currency,
        winners_status,
        winning_coupons,
        CASE
            WHEN contains(dq_flags, 'pozo_plata_equals_oro') THEN 'pozo_plata_equals_oro'
            WHEN contains(dq_flags, 'amount_sources_differ') THEN 'amount_sources_differ'
            WHEN pool_amount IS NULL THEN 'no_amount'
        END AS excluded_reason
    FROM silver_prizes
),
chained AS (
    SELECT
        prizes.*,
        lag(draw_date) OVER (PARTITION BY prize ORDER BY draw_date) AS previous_draw_date,
        lag(pool_amount) OVER (PARTITION BY prize ORDER BY draw_date) AS previous_pool_amount,
        lag(winners_status) OVER (PARTITION BY prize ORDER BY draw_date) AS previous_winners_status
    FROM prizes
    WHERE excluded_reason IS NULL
),
compared AS (
    SELECT
        chained.*,
        pool_amount - previous_pool_amount AS pool_change,
        CASE previous_winners_status
            WHEN 'no_winners' THEN 'up'
            WHEN 'winners' THEN 'down'
        END AS expected_direction,
        CASE
            WHEN pool_amount > previous_pool_amount THEN 'up'
            WHEN pool_amount < previous_pool_amount THEN 'down'
            WHEN pool_amount = previous_pool_amount THEN 'same'
        END AS observed_direction
    FROM chained
)
SELECT
    game,
    draw_date,
    prize,
    pool_amount,
    currency,
    winners_status,
    winning_coupons,
    CAST(NULL AS varchar) AS excluded_reason,
    previous_draw_date,
    previous_pool_amount,
    previous_winners_status,
    pool_change,
    expected_direction,
    observed_direction,
    expected_direction = observed_direction AS as_expected
FROM compared
UNION ALL
SELECT
    game,
    draw_date,
    prize,
    pool_amount,
    currency,
    winners_status,
    winning_coupons,
    excluded_reason,
    CAST(NULL AS date) AS previous_draw_date,
    CAST(NULL AS decimal(18, 2)) AS previous_pool_amount,
    CAST(NULL AS varchar) AS previous_winners_status,
    CAST(NULL AS decimal(18, 2)) AS pool_change,
    CAST(NULL AS varchar) AS expected_direction,
    CAST(NULL AS varchar) AS observed_direction,
    CAST(NULL AS boolean) AS as_expected
FROM prizes
WHERE excluded_reason IS NOT NULL
ORDER BY 2, 3
