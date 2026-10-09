# Permanent implementation and QA rule

Aegis is in PRODUCT-FIRST BUILD MODE. The priority is a functioning, inspectable
trading research application. Reversible product work should move quickly and must
not be blocked by review ceremony that is disproportionate to its blast radius.

Before planning or changing Core chat, Intake, memory, model routing, or Aegis, read
[the standing product direction](docs/CORE_CHAT_VISION.md), including its dated
operator corrections. Documentation is not proof of capability; verify by running.

For ordinary reversible Aegis product changes under `app/products/aegis/`, product
tests, and product documentation, the builder may implement and run the relevant
checks without a separate independent QA agent after every bounded edit. Preserve
test evidence and use milestone QA when a vertical slice is ready for review.

Independent QA and explicit Core governance remain mandatory for changes that affect:
- live-money execution, exchange enablement, broker/order paths, or risk limits;
- secrets, credentials, authentication, provider authority, or permissions;
- destructive operations, database migrations, or retained canonical data;
- shared Core contracts, product-isolation boundaries, or governance enforcement.

Core owns generic intelligence, authority, memory/knowledge, provider integration,
and shared runtime. Products consume Core; Core imports neither product. Preserve
product-private knowledge and credentials.

Triad is intentionally suspended (operator decision 2026-10-09). Its autonomous
improvement game does not run while Aegis is built; it resumes later with Aegis as a
base to work with. Scheduled autonomy is disabled by `DailySchedule` record `c99fa831`
(2026-10-09) and may be re-enabled only by an explicit operator decision through the
operator route. Aegis remains human-directed. Exchange stays CLOSED and live trading
stays disabled until separately and explicitly authorized.

Historical P2P evidence remains preserved through the canonical Aegis alias.
