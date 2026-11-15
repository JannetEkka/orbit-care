# Security

Orbit holds health information about a vulnerable person, so it is built to keep that information inside the family's circle.

## What protects the data

- **Passcodes:** salted scrypt hashes (N=2^14), compared in constant time. A keyed HMAC fingerprint finds the right member without trying every hash. Weak codes (`123456`, `111111`) are refused, two people cannot share one, and the orbit locks for 15 minutes after 5 wrong attempts.
- **Sessions:** a signed, expiring token in a cookie that is HttpOnly, Secure and SameSite=Strict, named with the `__Host-` prefix in production. Every request re-reads the member, so removing a person ends their access at once.
- **Cross-site request forgery:** SameSite=Strict, plus a custom header that a cross-site form cannot send on every state-changing request.
- **Roles:** checked on every route. A doctor can only read. The bedside screen can only confirm a dose, answer "how are you" and press Help.
- **Input:** strict Pydantic models with length and pattern limits, and unknown fields are rejected. SQL is parameterised, and the only field names used in queries come from a fixed allow-list. Email headers are stripped of line breaks.
- **Output:** a Content-Security-Policy with no inline script and no third-party script. All server text is inserted with `textContent`. The page also sets `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, HSTS and same-origin COOP/CORP.
- **Secrets:** only in the host's environment (Render environment variables, or Secret Manager on Google Cloud), never in the repository.
- **The AI:** Gemini never decides anything. It receives computed facts, its text is rejected if it adds a number, and the allowed note tags are a fixed list.
- **Abuse limits:** sign-in and creation are rate-limited per address, each orbit has a daily email cap, and sample orbits never send email and are deleted after 24 hours.
- **Dependencies:** pinned, and checked for known vulnerabilities with `pip-audit` on every CI run.

## Reporting a problem

Please open a private security advisory on this repository (Security → Report a vulnerability) rather than a public issue.
