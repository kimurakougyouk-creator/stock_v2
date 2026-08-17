"""
証券会社管理モジュール
Version 3.1
"""

SUPPORTED_BROKERS = {
    "SBI": {
        "name": "SBI証券",
        "enabled": True,
    },
    "RAKUTEN": {
        "name": "楽天証券",
        "enabled": False,
    },
    "MOOMOO": {
        "name": "moomoo証券",
        "enabled": False,
    },
    "IBKR": {
        "name": "Interactive Brokers",
        "enabled": False,
    },
}


def get_enabled_broker():
    for broker_id, info in SUPPORTED_BROKERS.items():
        if info["enabled"]:
            return broker_id, info
    return None, None


if __name__ == "__main__":
    broker_id, broker = get_enabled_broker()
    if broker:
        print(f"現在使用中: {broker['name']} ({broker_id})")
    else:
        print("有効な証券会社がありません。")
