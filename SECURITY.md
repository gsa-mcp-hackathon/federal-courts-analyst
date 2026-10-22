# Security Policy

As a U.S. Government agency, the General Services Administration (GSA) takes seriously our responsibility to protect the public's information, including financial and personal information, from unwarranted disclosure.

Software developed by the U.S. General Services Administration (GSA) is subject to the GSA Vulnerability Disclosure Policy.

Please consult our policy for:

How to submit a report if you believe you have discovered a vulnerability.
GSA's coordinated disclosure policy.
Information on how you may conduct security research on GSA developed software and systems.
Important legal and policy guidelines.

## Supported Versions

Use this section to tell people about which versions of your project are
currently being supported with security updates.

| Version (Branch) | Supported          |
| ------- | ------------------ |
| main   | :white_check_mark: |
| other  | :x:

## Security Researchers

Security researchers shall:

- Make every effort to avoid privacy violations, degradation of user experience, disruption to production systems, and destruction or manipulation of data.
- Only use exploits to the extent necessary to confirm a vulnerability. Do not use an exploit to compromise or exfiltrate data, establish command line access and/or persistence, or use the exploit to "pivot" to other systems. Once you've established that a vulnerability exists, or encountered any of the sensitive data outlined above, you must stop your test and notify us immediately.
- Keep confidential any information about discovered vulnerabilities for up to 90 calendar days after you have notified GSA. For details, please review Coordinated Disclosure.

## This project's security posture

See the [threat model](docs/security/threat-model.md) and
[ADR 0010](docs/adr/0010-guardrail-policy-layer.md). In short:

- The server serves public statistics. IDB party names never enter its
  database, and an output scanner withholds any result that matches one.
- The HTTP endpoint sends security headers, enforces a CORS allowlist (closed
  by default), a request size limit and a per-client rate limit, and can
  require a bearer token (`HTTP_BEARER_TOKEN`). **Set the token for any
  deployment reachable from the internet.** `/health` and `/version` stay open
  for platform health checks.
- The container runs as a non-root user and is meant to run with a read-only
  root filesystem (`make docker-run` shows the flags).
- The request desk ([ADR 0013](docs/adr/0013-request-desk.md)) is the only
  write path, and it writes only to its own sandbox store; the official data
  stays read-only. Its staff routes need `DESK_STAFF_TOKEN` (off when
  unset), writes are rate limited, question and answer text is screened for
  judge-level requests and party names before it's stored, every write is
  in an append-only audit log, and the agent is never offered a desk tool.
- Secrets come only from the environment and are redacted from logs. CI runs
  `pip-audit`, `bandit` and `detect-secrets` (`make security` locally).

Never commit secrets: keep API keys in environment variables or `.env`
(git-ignored), not in source.
