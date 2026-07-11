# Module: `observability`

SNS alerts topic + optional email subscription.

**Status:** foundation landed in **PR-014** (new resources — nothing to import). Phase 4
fleshes it out: log retention (PR-023), the CloudWatch dashboard (PR-024), alarms wired
to this topic (PR-025), the scraper HTTP-status metric (PR-026), the optional S3
object-count emitter (PR-027), and the tfvars-driven email subscription docs (PR-028).

## Behavior

- `aws_sns_topic.alerts` (`loteria-alerts-<environment>`) always exists.
- `aws_sns_topic_subscription.email_alerts` is created only when `alert_email` is
  non-empty (root var `alert_email`, default `""`). **The recipient must click the
  confirmation link AWS emails** — until then the subscription is "pending confirmation"
  and no alerts are delivered.

## Inputs / outputs

- Inputs: `environment`, `alert_email` (optional).
- Outputs: `alerts_topic_arn`.
