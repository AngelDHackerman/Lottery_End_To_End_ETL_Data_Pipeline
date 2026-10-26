"""What knows no country (docs/uruguay/DESIGN.md, D1).

- http_client: the only way ``sorteos`` talks to the network — rate limit, retries and the
               privacy blocklist.
- bronze:      local raw store + manifest (the manifest is the cache, not bronze).
"""
