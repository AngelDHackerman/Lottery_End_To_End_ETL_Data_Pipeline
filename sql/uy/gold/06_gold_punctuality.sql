-- gold_punctuality — does the Quiniela start on time, and how long does it take? (UY-032, UY-044.2)
--
-- Grain: (game, scope, year), as in gold_quiniela_repeats. The times are Montevideo wall-clock
-- times as the extract publishes them (P2); the 5 de Oro publishes none.
--
-- Expected: the Vespertina starts at 15:00 and the Nocturna at 21:00 (the start the site
-- gives for 97 % and 99 % of their draws, in that order). Observed: the share of draws that start at that
-- minute, the mean offset in minutes, and how long the draw takes: to the first ball and to
-- the end. The longest and shortest durations stay in, so a typed-wrong hour shows.
--
-- Excludes, and counts, the draws flagged `timing_out_of_order` (D22) and those missing any
-- of the three times.
WITH schedule AS (
    SELECT game, scheduled_start, scheduled_minute
    FROM (
        VALUES ('quiniela_vespertina', '15:00', 900), ('quiniela_nocturna', '21:00', 1260)
    ) AS t (game, scheduled_start, scheduled_minute)
),
per_draw AS (
    SELECT
        d.game,
        d.draw_date,
        s.scheduled_start,
        hour(d.started_local) * 60 + minute(d.started_local) - s.scheduled_minute AS start_offset,
        date_diff('minute', d.started_local, d.first_ball_local) AS to_first_ball,
        date_diff('minute', d.started_local, d.ended_local) AS duration,
        (
            d.started_local IS NULL
            OR d.first_ball_local IS NULL
            OR d.ended_local IS NULL
            OR contains(d.dq_flags, 'timing_out_of_order')
        ) AS excluded
    FROM silver_draws AS d
    INNER JOIN schedule AS s ON s.game = d.game
),
scoped AS (
    SELECT 'year' AS scope, CAST(year(draw_date) AS integer) AS year, per_draw.* FROM per_draw
    UNION ALL
    SELECT 'total' AS scope, 0 AS year, per_draw.* FROM per_draw
),
measured AS (
    SELECT
        game,
        scope,
        year,
        scheduled_start,
        count_if(NOT excluded) AS draws,
        count_if(excluded) AS draws_excluded,
        count_if(NOT excluded AND start_offset = 0) AS draws_on_schedule,
        avg(CAST(start_offset AS double)) FILTER (WHERE NOT excluded) AS mean_start_offset_minutes,
        avg(CAST(to_first_ball AS double)) FILTER (WHERE NOT excluded) AS mean_minutes_to_first_ball,
        avg(CAST(duration AS double)) FILTER (WHERE NOT excluded) AS mean_duration_minutes,
        min(duration) FILTER (WHERE NOT excluded) AS min_duration_minutes,
        max(duration) FILTER (WHERE NOT excluded) AS max_duration_minutes,
        count_if(NOT excluded AND duration > 60) AS draws_over_60_minutes
    FROM scoped
    GROUP BY game, scope, year, scheduled_start
)
SELECT
    game,
    scope,
    NULLIF(year, 0) AS year,
    scheduled_start,
    draws,
    draws_excluded,
    draws_on_schedule,
    CAST(draws_on_schedule AS double) / NULLIF(draws, 0) AS observed_on_schedule_rate,
    CAST(1 AS double) AS expected_on_schedule_rate,
    mean_start_offset_minutes,
    mean_minutes_to_first_ball,
    mean_duration_minutes,
    min_duration_minutes,
    max_duration_minutes,
    draws_over_60_minutes
FROM measured
ORDER BY game, scope, year
