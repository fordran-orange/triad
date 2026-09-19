"""Contracts and truthful broker shells. No network or credential operations."""

from trading_core.integrations.contracts import IntegrationRecord

BROKER_CAPABILITIES = (
    "ACCOUNT_READ",
    "BALANCE_READ",
    "POSITIONS_READ",
    "ORDERS_READ",
    "ORDER_PLACE",
    "ORDER_CANCEL",
    "ORDER_REPLACE",
    "REALTIME_QUOTES",
    "HISTORICAL_BARS",
    "OPTIONS_DATA",
    "OPTIONS_CHAIN",
    "STREAMING_DATA",
)


class CapabilityUnavailable(RuntimeError):
    pass


class IntegrationAdapter:
    def __init__(self, definition: IntegrationRecord):
        self.definition = definition

    def metadata(self):
        return self.definition.model_dump(mode="json")

    def capabilities(self):
        return dict(self.definition.capabilities)

    def require(self, capability):
        if self.capabilities().get(capability) != "IMPLEMENTED":
            raise CapabilityUnavailable("Capability is not implemented: " + capability)
        if not self.definition.enabled or not self.definition.configured:
            raise CapabilityUnavailable("Integration is not enabled and configured")

    def authenticate(self):
        raise CapabilityUnavailable("Authentication is not implemented for this shell")

    def disconnect(self):
        raise CapabilityUnavailable("No configured connection exists")

    def health_check(self):
        return {
            "status": "NOT_CONFIGURED",
            "connected": False,
            "detail": "Shell only; no account or network test performed",
        }


class BrokerAdapter(IntegrationAdapter):
    def get_accounts(self):
        self.require("ACCOUNT_READ")
        raise CapabilityUnavailable("Account transport not implemented")

    def get_balances(self, account_id):
        self.require("BALANCE_READ")
        raise CapabilityUnavailable("Balance transport not implemented")

    def get_positions(self, account_id):
        self.require("POSITIONS_READ")
        raise CapabilityUnavailable("Position transport not implemented")

    def get_orders(self, account_id):
        self.require("ORDERS_READ")
        raise CapabilityUnavailable("Order read transport not implemented")

    def get_order(self, account_id, order_id):
        return self.get_orders(account_id)

    def place_order(self, *args, **kwargs):
        raise PermissionError("Live execution denied by Core policy")

    def cancel_order(self, *args, **kwargs):
        raise PermissionError("Live execution denied by Core policy")

    def replace_order(self, *args, **kwargs):
        raise PermissionError("Live execution denied by Core policy")

    def get_quotes(self, symbols):
        self.require("REALTIME_QUOTES")
        raise CapabilityUnavailable("Quote transport not implemented")

    def stream_events(self):
        self.require("STREAMING_DATA")
        raise CapabilityUnavailable("Streaming transport not implemented")


class SchwabBrokerAdapter(BrokerAdapter):
    def __init__(self):
        super().__init__(
            IntegrationRecord(
                integration_id="schwab",
                name="Charles Schwab",
                provider="Charles Schwab",
                category="BROKER",
                authentication_type="Official Trader API authorization; not configured",
                capabilities={c: "UNVERIFIED" for c in BROKER_CAPABILITIES},
                documentation_reference=(
                    "https://developer.schwab.com/products/trader-api--individual",
                    "https://www.schwab.com/learn/story/ways-ai-trading-tools-help-increase-efficiency",
                ),
                transports=({"transport": "REST", "domain": "Trader API", "status": "UNVERIFIED"},),
                permissions_required=("separate operator account authorization",),
                notes=(
                    "Official Trader API documented; local account/data transport not implemented or tested.",
                    "Exact endpoints, entitlements and rate limits require official app registration review.",
                    "Live order actions remain denied.",
                ),
            )
        )


class RobinhoodBrokerAdapter(BrokerAdapter):
    def __init__(self):
        super().__init__(
            IntegrationRecord(
                integration_id="robinhood",
                name="Robinhood",
                provider="Robinhood",
                category="BROKER",
                authentication_type="Official domain-specific authorization; not configured",
                capabilities={c: "UNVERIFIED" for c in BROKER_CAPABILITIES},
                documentation_reference=(
                    "https://robinhood.com/us/en/support/articles/agentic-trading-overview/",
                    "https://robinhood.com/us/en/support/articles/trading-with-your-agent/",
                    "https://docs.robinhood.com/crypto/trading/",
                ),
                transports=(
                    {
                        "transport": "MCP",
                        "domain": "Agentic Trading: equities, options and crypto; account permissions differ",
                        "endpoint": "https://agent.robinhood.com/mcp/trading",
                        "status": "UNVERIFIED",
                    },
                    {
                        "transport": "REST",
                        "domain": "Crypto Trading API only",
                        "status": "UNVERIFIED",
                    },
                    {
                        "transport": "SDK",
                        "domain": "No official SDK verified",
                        "status": "UNAVAILABLE",
                    },
                ),
                permissions_required=(
                    "separate operator authorization per supported account domain",
                ),
                notes=(
                    "Official Trading MCP and separate crypto API are distinct interfaces.",
                    "No unofficial website automation, credentials, account access or order transport implemented.",
                    "Vendor-advertised capabilities are not local verified capabilities.",
                ),
            )
        )


class MarketDataAdapter(IntegrationAdapter):
    def get_capabilities(self):
        return self.capabilities()

    def fetch_historical_bars(self, request):
        raise CapabilityUnavailable("Historical transport not implemented")

    def fetch_latest_quote(self, symbol):
        raise CapabilityUnavailable("Quotes not implemented")

    def fetch_trades(self, request):
        raise CapabilityUnavailable("Trades not implemented")

    def fetch_order_book(self, symbol):
        raise CapabilityUnavailable("Order book not implemented")

    def fetch_options_chain(self, symbol):
        raise CapabilityUnavailable("Options chain not implemented")

    def stream_quotes(self, symbols):
        raise CapabilityUnavailable("Quote stream not implemented")

    def stream_trades(self, symbols):
        raise CapabilityUnavailable("Trade stream not implemented")
