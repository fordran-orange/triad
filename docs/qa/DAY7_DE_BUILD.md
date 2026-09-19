# D/E: external integration registry and broker shells

Generic typed integration, connection, candidate and data-request records; extensible category taxonomy; common adapter, broker and market-data contracts. Core owns immutable integration definitions/connections; products can discover sanitized global metadata while candidates and use requests retain product ownership. Proposals require active same-product assignments and cannot approve/install themselves. Operator decisions have a constrained lifecycle; marking implemented requires registered capability and independent exact-commit QA. No credential fields or arbitrary module installation exist.

Schwab and Robinhood shells use official documentation references. Robinhood official Trading MCP, crypto REST and unverified SDK are distinguished by domain. All broker operations are unimplemented, capabilities UNVERIFIED, status NOT_CONFIGURED; no account tests. All live order actions fail closed regardless of metadata. Health checks explicitly say shell-only and perform no network operation.

Official sources were reviewed during Day7 research; preserved source notes logs/day7-integration-research.md. No specific external historical vendor is claimed. D/E are combined because shells only supply metadata and denied contract methods.
