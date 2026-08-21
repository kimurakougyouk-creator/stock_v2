# CI safety contract

Pull-request CI must remain safe to run without TWS/Gateway and without real credentials.

Required behavior:

- scan tracked files for likely committed secrets before pytest;
- use placeholder-only repository configuration;
- run the full automated test suite;
- never transmit a Paper order from CI;
- never enable Live Trading from CI;
- keep broker network interactions mocked in unit tests.

External IBKR Paper handshake validation belongs to the explicit local foundation audit when TWS/Gateway Paper is available.
