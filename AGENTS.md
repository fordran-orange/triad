# Permanent implementation and QA rule

Aegis is in PRODUCT-FIRST BUILD MODE. The priority is a functioning, inspectable
trading research application. Reversible product work should move quickly and must
not be blocked by review ceremony that is disproportionate to its blast radius.

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

Triad's autonomous improvement game and scheduled autonomy are suspended while Aegis
is built. Aegis remains human-directed. Exchange stays CLOSED and live trading stays
disabled until separately and explicitly authorized.

Historical P2P evidence remains preserved through the canonical Aegis alias.
