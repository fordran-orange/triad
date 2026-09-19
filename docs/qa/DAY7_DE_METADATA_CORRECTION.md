# D/E public-metadata correction

URL scheme matching is now case-insensitive; normalized API-key/access-token/refresh-token variants and credential/header containers are rejected. IntegrationConnection is validated at host writes and revalidated/quarantined before shared catalog overlays. Invalid legacy connection status objects cannot leak into product metadata. Core candidate/definition/QA adoption binding from the preceding correction is retained.

Root combined D/E/F regression: 22 passed in45.48seconds. Fresh independent QA required; both earlier failure reports remain preserved.
