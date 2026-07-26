"""
AI資産運用プラットフォーム
System Configuration
"""

SYSTEM_NAME = "AI Asset Platform"

SYSTEM_VERSION = "4.0-dev"

RUN_MODE = "DEVELOPMENT"

ENABLE_AI = True

ENABLE_PAPER_TRADING = True

SUPPORTED_MARKETS = [
    "JP_STOCK"
]

SUPPORTED_BROKERS = [
    "SBI"
]

if __name__ == "__main__":
    print("=" * 40)
    print(SYSTEM_NAME)
    print("Version :", SYSTEM_VERSION)
    print("Mode    :", RUN_MODE)
    print("AI      :", ENABLE_AI)
    print("Paper   :", ENABLE_PAPER_TRADING)
    print("Markets :", ", ".join(SUPPORTED_MARKETS))
    print("Broker  :", ", ".join(SUPPORTED_BROKERS))
    print("=" * 40)
