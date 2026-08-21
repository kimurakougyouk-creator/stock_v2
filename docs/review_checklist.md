# Pre-merge review checklist

Before merging a foundation-hardening PR:

- changed files match the declared scope;
- secret scan passes;
- full pytest passes;
- no real credentials appear in diff;
- no Live Trading setting is enabled;
- no risk limit is weakened;
- no CI step transmits an order;
- documentation distinguishes verified support from target scope;
- unresolved external checks remain explicitly open.
