"""DuckDB connection + raw table schemas."""
import duckdb
from .config import DB_PATH, DATA_DIR, IST

RAW_SCHEMAS = {
    "raw_event_log": {
        "id": "VARCHAR PRIMARY KEY", "user_name": "VARCHAR", "session_id": "VARCHAR", "country": "VARCHAR",
        "city": "VARCHAR", "region": "VARCHAR", "ip_address": "VARCHAR", "device": "VARCHAR", "platform": "VARCHAR",
        "browser": "VARCHAR", "language": "VARCHAR", "time_ist": "VARCHAR", "page_link": "VARCHAR",
        "event_name": "VARCHAR", "extra_data": "JSON", "created_at": "TIMESTAMPTZ", "value": "VARCHAR",
        "referrer": "VARCHAR", "user_id": "VARCHAR", "visitor_id": "VARCHAR", "phone_no": "VARCHAR",
    },
    "raw_users": {
        "id": "VARCHAR", "email": "VARCHAR", "name": "VARCHAR", "phone_no": "VARCHAR", "skin_type": "VARCHAR",
        "skin_concerns": "JSON", "role": "VARCHAR", "gender": "VARCHAR", "wallet_balance": "DOUBLE",
        "referral_code": "VARCHAR", "used_referral_code": "VARCHAR", "created_at": "TIMESTAMPTZ",
        "phone_verified": "BOOLEAN", "skin_score": "INTEGER",
    },
    "raw_orders": {
        "id": "VARCHAR", "user_id": "VARCHAR", "name": "VARCHAR", "email": "VARCHAR", "phone": "VARCHAR",
        "pincode": "VARCHAR", "items": "JSON", "total": "DOUBLE", "savings": "DOUBLE", "status": "VARCHAR",
        "created_at": "TIMESTAMPTZ", "delivery_fee": "VARCHAR", "coupon_discount": "VARCHAR",
        "products_total": "VARCHAR", "state": "VARCHAR", "city": "VARCHAR", "wallet_amount_used": "DOUBLE",
        "coupon_code": "VARCHAR", "payment_status": "VARCHAR", "payment_method": "VARCHAR",
        "paid_at": "TIMESTAMPTZ", "visitor_id": "VARCHAR", "session_id": "VARCHAR",
        "delivered_at": "TIMESTAMPTZ", "discount": "DOUBLE",
        "handling_fee": "VARCHAR", "cashback_amount": "DOUBLE", "cashback_percent": "DOUBLE", "payment_failed_reason": "VARCHAR",
        "rider_id": "VARCHAR", "courier_partner": "VARCHAR", "tracking_id": "VARCHAR", "metadata": "JSON",
    },
    "raw_quiz_results": {
        "id": "VARCHAR", "user_id": "VARCHAR", "gender": "VARCHAR", "age": "VARCHAR", "skin_type": "VARCHAR",
        "created_at": "TIMESTAMPTZ", "completed_at": "TIMESTAMPTZ", "quiz_number": "INTEGER",
        "guest_session_id": "VARCHAR",
    },
    "raw_visitor_links": {
        "visitor_id": "VARCHAR", "user_id": "VARCHAR", "guest_session_id": "VARCHAR", "session_id": "VARCHAR",
        "linked_at": "TIMESTAMPTZ",
    },
    "raw_catalog_roopsee": {
        "product_uid": "VARCHAR", "product_name": "VARCHAR", "brand": "VARCHAR", "category_l1": "VARCHAR",
        "product_type_l2": "VARCHAR", "mrp": "DOUBLE", "selling_price": "DOUBLE",
    },
    "raw_catalog_master": {
        "product_id": "VARCHAR", "product_name": "VARCHAR", "brand": "VARCHAR", "category_l1": "VARCHAR",
        "category_l2": "VARCHAR", "mrp": "DOUBLE", "selling_price": "DOUBLE",
    },
    # Roop (the skin assistant) chats. Only the columns the dashboard needs: prompt_messages / raw_response (fine-tuning data) are never pulled.
    "raw_chat_logs": {
        "id": "VARCHAR", "created_at": "TIMESTAMPTZ", "conversation_id": "VARCHAR", "user_id": "VARCHAR", "guest_session_id": "VARCHAR", "intent": "VARCHAR",
        "user_message": "VARCHAR", "reply": "VARCHAR", "product_ids": "JSON", "has_profile": "BOOLEAN", "model": "VARCHAR", "latency_ms": "INTEGER",
        "error": "VARCHAR", "rating": "INTEGER", "prompt_tokens": "INTEGER", "completion_tokens": "INTEGER", "product_id": "VARCHAR",
    },
    "raw_meta_insights": {
        "account_id": "VARCHAR", "date": "DATE", "campaign_id": "VARCHAR", "campaign_name": "VARCHAR", "adset_id": "VARCHAR", "adset_name": "VARCHAR",
        "ad_id": "VARCHAR", "ad_name": "VARCHAR", "spend": "DOUBLE", "impressions": "BIGINT", "reach": "BIGINT", "frequency": "DOUBLE", "clicks": "BIGINT",
        "link_clicks": "BIGINT", "ctr": "DOUBLE", "cpc": "DOUBLE", "cpm": "DOUBLE", "purchases": "DOUBLE", "purchase_value": "DOUBLE", "add_to_cart": "DOUBLE",
        "initiate_checkout": "DOUBLE", "view_content": "DOUBLE", "landing_page_views": "DOUBLE", "actions": "JSON",
    },
    "raw_meta_entities": {
        "account_id": "VARCHAR", "entity_type": "VARCHAR", "entity_id": "VARCHAR", "name": "VARCHAR", "campaign_id": "VARCHAR", "adset_id": "VARCHAR",
        "status": "VARCHAR", "effective_status": "VARCHAR", "objective": "VARCHAR", "daily_budget": "DOUBLE", "lifetime_budget": "DOUBLE",
        "thumbnail_url": "VARCHAR", "created_time": "TIMESTAMPTZ",
    },
    "raw_customer_address": {
        "id": "BIGINT", "user_id": "VARCHAR", "city": "VARCHAR", "state": "VARCHAR", "pincode": "VARCHAR",
        "is_default": "BOOLEAN", "created_at": "TIMESTAMPTZ", "latitude": "DOUBLE", "longitude": "DOUBLE",
        "delivery_address": "VARCHAR", "formatted_address": "VARCHAR", "nearby_landmark": "VARCHAR", "full_name": "VARCHAR",
        "phone": "VARCHAR", "email": "VARCHAR", "location_source": "VARCHAR", "updated_at": "TIMESTAMPTZ",
    },
}

META_DDL = """
CREATE TABLE IF NOT EXISTS etl_runs (run_id BIGINT, step VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP,
                                     rows BIGINT, note VARCHAR);
"""


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    con.execute(f"SET TimeZone='{IST}'")
    con.execute("SET enable_progress_bar=false")
    if not read_only:
        init_raw(con)
    return con


def init_raw(con) -> None:
    for t, cols in RAW_SCHEMAS.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {t} ({', '.join(f'{c} {d}' for c, d in cols.items())})")
        for c, d in cols.items():  # schema migration: columns added in later versions
            con.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} {d.split(' PRIMARY')[0]}")
    con.execute(META_DDL)


def log_run(con, step: str, started, rows: int | None = None, note: str = "") -> None:
    """One row per pipeline step in etl_runs (what ran, when, how many rows, any warning). Never lets logging break a run."""
    import time
    from datetime import datetime
    try:
        con.execute("INSERT INTO etl_runs VALUES (?, ?, ?, ?, ?, ?)", [int(time.time() * 1000), step, started, datetime.now(), rows, note or None])
    except Exception:
        pass


import threading
DB_LOCK = threading.RLock()  # serialises short writes (extract inserts, exclusion edits) against API reads
TRANSFORM_LOCK = threading.Lock()  # one rebuild at a time; readers are NOT blocked by it (the rebuild is a single transaction)
