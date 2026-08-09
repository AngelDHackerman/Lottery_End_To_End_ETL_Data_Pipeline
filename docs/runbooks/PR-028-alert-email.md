# PR-028 — Wire the SNS email subscription via tfvars

**Scope:** one new tracked file (`terraform/terraform.tfvars.example`), a hardened
`alert_email` variable, and the documentation of a step Terraform **cannot** perform.

**Why it matters more than its size suggests:** PR-025 shipped six alarms into a topic with
**zero subscribers**. They evaluated correctly, transitioned correctly, and notified nobody.
This PR is what turns them into alerts.

---

## 1. The public/private file pair

| File | Tracked? | Contents |
|---|---|---|
| `terraform/terraform.tfvars.example` | **yes** | placeholders only |
| `terraform/terraform.tfvars` | **no** — `.gitignore:280` `*.tfvars` | the real address |

The `.example` suffix is what takes the template out of the `*.tfvars` glob. Verify both
sides rather than trusting it:

```bash
git check-ignore -v terraform/terraform.tfvars.example   # must print NOTHING
git check-ignore -v terraform/terraform.tfvars           # must print the rule
git grep -In "your-real-address" -- .                    # must print NOTHING
```

All three confirmed on 2026-08-09.

> Historical note: the real address **did** leak into three tracked docs and was scrubbed
> during PR-025. `terraform.tfvars.example` is the file most likely to reintroduce it,
> because the natural instinct when filling in a template is to type the real value. Copy it
> to `terraform.tfvars` first, then edit.

## 2. Setting it

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars:  alert_email = "you@example.com"
terraform apply
```

`alert_email` now has a plan-time regex validation. SNS accepts almost any string as an
email endpoint and simply never delivers to a bad one, so without the check a typo produces
an alarm that silently notifies nobody — the exact failure this PR exists to remove.

## 3. ⚠️ The step Terraform cannot do

**AWS emails a confirmation link and someone has to click it.** There is no API to confirm
an email subscription on the subscriber's behalf — that is deliberate, it is what stops
anyone from subscribing your address to their topic.

Consequences worth internalising:

- **`terraform apply` reports the subscription as created either way.** A green apply is
  **not** proof that alerts will arrive.
- Until the click, the subscription's ARN is the literal string `PendingConfirmation`.
- The link **expires after 3 days**. If you miss it:
  `terraform apply -replace='module.observability.aws_sns_topic_subscription.email_alerts[0]'`
  sends a fresh one.
- The subject is generic — *"AWS Notification - Subscription Confirmation"* — and it
  regularly lands in spam.
- Terraform's `confirmation_timeout_in_minutes = 1` is **not** how long you have to click;
  it is only how long Terraform waits before giving up on observing confirmation.

Check the state:

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:us-east-1:<account-id>:loteria-alerts-prod \
  --query 'Subscriptions[].[Protocol,Endpoint,SubscriptionArn]' --output table
```

A confirmed subscription shows a real ARN ending in a UUID. An unconfirmed one shows
`PendingConfirmation`.

## 4. End-to-end verification

Confirming the subscription proves SNS can reach the inbox. It does **not** prove an *alarm*
can reach SNS — that additionally needs the topic policy to allow CloudWatch, and the alarm
to carry the right `alarm_actions`. Test both links of the chain.

### 4a. The topic can deliver

```bash
aws sns publish \
  --topic-arn arn:aws:sns:us-east-1:<account-id>:loteria-alerts-prod \
  --subject "loteria smoke test" \
  --message "If this arrives, the SNS subscription is confirmed and delivering."
```

### 4b. A real alarm can deliver — the one that matters

`set-alarm-state` drives a genuine state transition, so this exercises the whole path
(alarm → `alarm_actions` → topic policy → subscription → inbox) rather than just the last
hop:

```bash
aws cloudwatch set-alarm-state \
  --alarm-name loteria-sfn-execution-failed-prod \
  --state-value ALARM \
  --state-reason "PR-028 end-to-end delivery test"
```

Then return it:

```bash
aws cloudwatch set-alarm-state \
  --alarm-name loteria-sfn-execution-failed-prod \
  --state-value OK --state-reason "PR-028 test complete"
```

Two notes on reading the result:

- **You will get ONE email, not two.** The alarms deliberately set `alarm_actions` and leave
  `ok_actions` unset (PR-025) — recovery mail on a weekly pipeline is noise.
- `describe-alarm-history` records the transition, which is useful evidence even if the mail
  is slow or filtered:

```bash
aws cloudwatch describe-alarm-history \
  --alarm-name loteria-sfn-execution-failed-prod \
  --history-item-type Action --max-records 5 \
  --query 'AlarmHistoryItems[].[Timestamp,HistorySummary]' --output table
```

A `Successfully executed action` line naming the SNS topic is the authoritative proof that
CloudWatch published. If that line exists but no mail arrives, the problem is the
subscription or the inbox, not the alarm.

### 4c. `set-alarm-state` is safe here

It writes a synthetic state transition and nothing else. It does not touch the pipeline, and
CloudWatch overwrites the forced state at the next real evaluation (5 minutes for this alarm,
which is also why it self-returns to OK anyway — PR-025's alarms are pulses, not sticky
states).

## 5. Plan impact

```
1 to add: module.observability.aws_sns_topic_subscription.email_alerts[0]
```

Nothing else changes. The topic itself has existed since PR-014.

If `alert_email` was already set in a local `terraform.tfvars` before this PR, the plan is
`0 to add` — the code change here is the tracked example file, the validation rule and this
runbook, none of which produce resources.

## 6. Out of scope

- Additional protocols (SMS, Slack via Chatbot, PagerDuty). The topic accepts more
  subscriptions; `alarm_actions` is already a list, so adding one is a one-line change.
- Per-alarm routing. All six alarms notify the same topic today.
