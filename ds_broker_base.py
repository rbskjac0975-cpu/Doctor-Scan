from abc import ABC, abstractmethod

class BrokerError(RuntimeError):
    """Explicit, user-visible broker failure (never swallowed into fake data)."""

class BrokerAdapter(ABC):
    name = "BASE"
    is_mock = False
    state = "DISCONNECTED"   # DISCONNECTED | AUTHENTICATING | CONNECTED | RECONNECTING | ERROR
    last_error = ""

    @abstractmethod
    def login(self): ...
    @abstractmethod
    def logout(self): ...
    @abstractmethod
    def get_intraday(self, symbol):
        """Today's (or last session's) 1-min candles: ts, open, high, low, close, volume."""
    @abstractmethod
    def get_sessions(self, symbol, n=20):
        """List of previous full-session 1-min DataFrames, oldest first (excludes today)."""
    def get_profile(self): raise NotImplementedError
    def get_instruments(self): raise NotImplementedError
    def get_quote(self, symbol): raise NotImplementedError
    def get_historical_candles(self, symbol, n=20): return self.get_sessions(symbol, n)
    def subscribe_symbols(self, symbols): raise NotImplementedError
    def unsubscribe_symbols(self, symbols): raise NotImplementedError
    def websocket_connect(self): raise NotImplementedError
    def websocket_disconnect(self): raise NotImplementedError
    def get_option_chain(self, symbol): raise NotImplementedError
    def get_order_book(self): raise NotImplementedError
    def get_positions(self): raise NotImplementedError
    def lot_size(self, symbol): return 1
