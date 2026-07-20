import shutil
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from src import amenities as amenities_module
from src import chatbot as chatbot_module
from src import main as main_module
from src import payments as payments_module
from src.main import DB_PATH, app, config
from src.rate_limit import BUCKETS
from src.schemas import AmenityAdviceRequest, ChatRequest
from src.security import internal_proxy_key


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_projects_endpoint():
    client = TestClient(app)
    response = client.get("/projects")
    assert response.status_code == 200
    assert any(project["slug"] == "vinhomes-ocean-park" for project in response.json())


def test_auth_register_login_and_me(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "DB_PATH", tmp_path / "auth.sqlite")
    BUCKETS.clear()
    client = TestClient(app)

    registered = client.post(
        "/auth/register",
        json={"name": "Nguyen An", "email": "AN@example.com", "password": "secret123"},
    )
    assert registered.status_code == 200
    body = registered.json()
    assert body["access_token"]
    assert body["user"]["email"] == "an@example.com"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "an@example.com"

    logged_in = client.post("/auth/login", json={"email": "an@example.com", "password": "secret123"})
    assert logged_in.status_code == 200
    assert logged_in.json()["user"]["name"] == "Nguyen An"
    BUCKETS.clear()


def test_auth_accepts_naive_pro_expiry_timestamp(monkeypatch, tmp_path):
    db_path = tmp_path / "auth_naive_pro.sqlite"
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    BUCKETS.clear()
    client = TestClient(app)

    registered = client.post(
        "/auth/register",
        json={"name": "Naive Pro", "email": "naive-pro@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_user SET pro_expires_at = datetime('now', '+30 days') WHERE email = ?", ("naive-pro@example.com",))
    conn.commit()
    conn.close()

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["is_pro"] is True
    BUCKETS.clear()


def test_auth_duplicate_and_invalid_login(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "DB_PATH", tmp_path / "auth.sqlite")
    BUCKETS.clear()


def test_payment_order_generates_vietqr_and_activates_pro(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "DB_PATH", tmp_path / "payment.sqlite")
    monkeypatch.setenv("MBBANK_ACCOUNT_NO", "123456789")
    monkeypatch.setenv("MBBANK_ACCOUNT_NAME", "HOMEVALUE AI")
    monkeypatch.setenv("PAYMENT_AGENT_PRO_AMOUNT_VND", "299000")
    BUCKETS.clear()
    client = TestClient(app)

    registered = client.post(
        "/auth/register",
        json={"name": "Nguyen An", "email": "pay@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    order_response = client.post("/payments/pro-order", json={"plan": "agent_pro_monthly"}, headers=headers)
    assert order_response.status_code == 200
    order = order_response.json()
    assert order["status"] == "pending"
    assert order["amount_vnd"] == 299000
    assert order["transfer_content"].startswith("HVPRO")
    assert "img.vietqr.io" in order["qr_image_url"]
    assert "amount=299000" in order["qr_image_url"]

    def fake_transactions(**kwargs):
        return [
            {
                "creditAmount": "299000",
                "debitAmount": "0",
                "description": f"Thanh toan {order['transfer_content']}",
                "addDescription": "",
                "refNo": "MB123",
            }
        ]

    monkeypatch.setattr(payments_module, "fetch_mbbank_transactions", fake_transactions)
    paid_response = client.post(f"/payments/{order['order_code']}/check", json={}, headers=headers)
    assert paid_response.status_code == 200
    paid = paid_response.json()
    assert paid["status"] == "paid"
    assert paid["matched_ref_no"] == "MB123"
    assert paid["pro_expires_at"]

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["is_pro"] is True
    BUCKETS.clear()


def test_credit_payment_generates_vietqr_and_adds_credits(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "DB_PATH", tmp_path / "payment_credits.sqlite")
    monkeypatch.setenv("MBBANK_ACCOUNT_NO", "123456789")
    monkeypatch.setenv("MBBANK_ACCOUNT_NAME", "HOMEVALUE AI")
    monkeypatch.setenv("PAYMENT_CREDIT_PACK_AMOUNT_VND", "50000")
    monkeypatch.setenv("PAYMENT_CREDIT_PACK_CREDITS", "100")
    BUCKETS.clear()
    client = TestClient(app)

    registered = client.post(
        "/auth/register",
        json={"name": "Nguyen An", "email": "credit@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    order_response = client.post("/payments/pro-order", json={"plan": "credits_100"}, headers=headers)
    assert order_response.status_code == 200
    order = order_response.json()
    assert order["status"] == "pending"
    assert order["amount_vnd"] == 50000
    assert order["credits_added"] == 100
    assert order["transfer_content"].startswith("HVCRD")
    assert "img.vietqr.io" in order["qr_image_url"]
    assert "amount=50000" in order["qr_image_url"]

    def fake_transactions(**kwargs):
        return [
            {
                "creditAmount": "50000",
                "debitAmount": "0",
                "description": f"Nap credit {order['transfer_content']}",
                "addDescription": "",
                "refNo": "MBCRD123",
            }
        ]

    monkeypatch.setattr(payments_module, "fetch_mbbank_transactions", fake_transactions)
    paid_response = client.post(f"/payments/{order['order_code']}/check", json={}, headers=headers)
    assert paid_response.status_code == 200
    paid = paid_response.json()
    assert paid["status"] == "paid"
    assert paid["credits_added"] == 100
    assert paid["credit_balance"] == 105

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["credit_balance"] == 105
    BUCKETS.clear()


def test_payment_order_requires_login(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "DB_PATH", tmp_path / "payment_auth.sqlite")
    BUCKETS.clear()
    client = TestClient(app)
    response = client.post("/payments/pro-order", json={"plan": "agent_pro_monthly"})
    assert response.status_code == 401
    BUCKETS.clear()
    client = TestClient(app)
    payload = {"name": "Nguyen An", "email": "an@example.com", "password": "secret123"}

    assert client.post("/auth/register", json=payload).status_code == 200
    duplicate = client.post("/auth/register", json=payload)
    assert duplicate.status_code == 400

    invalid = client.post("/auth/login", json={"email": "an@example.com", "password": "wrong123"})
    assert invalid.status_code == 401
    BUCKETS.clear()


def test_price_snapshots_endpoint():
    client = TestClient(app)
    response = client.get("/price-snapshots", params={"project": "vinhomes-smart-city", "property_type": "apartment"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_verified_transactions_requires_admin_key():
    client = TestClient(app)
    response = client.post(
        "/verified-transactions",
        json={
            "project": "vinhomes-smart-city",
            "property_type": "apartment",
            "purpose": "sale",
            "transaction_price_vnd": 1_000_000,
            "area_m2": 54.2,
        },
    )
    assert response.status_code == 401


def test_verified_transactions_auth_runs_before_body_validation():
    client = TestClient(app)
    response = client.post("/verified-transactions", json={"foo": "bar"})
    assert response.status_code == 401


def test_valuation_rate_limit_returns_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_VALUATION_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_VALUATION_WINDOW_SECONDS", "60")
    BUCKETS.clear()
    client = TestClient(app)
    payload = {
        "project": "vinhomes-smart-city",
        "property_type": "apartment",
        "purpose": "sale",
        "area_m2": 54.2,
        "bedrooms": 2,
    }

    assert client.post("/valuation", json=payload).status_code == 200
    assert client.post("/valuation", json=payload).status_code == 200
    response = client.post("/valuation", json=payload)
    assert response.status_code == 429
    BUCKETS.clear()


def test_public_api_requires_frontend_proxy_header():
    client = TestClient(app)
    payload = {
        "project": "vinhomes-smart-city",
        "property_type": "apartment",
        "purpose": "sale",
        "area_m2": 54.2,
        "bedrooms": 2,
    }

    blocked = client.post("/valuation", json=payload, headers={"host": "apivinhomes.solanai.us"})
    assert blocked.status_code == 403

    allowed = client.post(
        "/valuation",
        json=payload,
        headers={"host": "apivinhomes.solanai.us", "X-Internal-Proxy-Key": internal_proxy_key()},
    )
    assert allowed.status_code == 200


def test_amenities_advice_endpoint_returns_map_searches(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "generate_answer", lambda *args, **kwargs: "- Ưu tiên kiểm tra map trước.")

    client = TestClient(app)
    response = client.post(
        "/amenities/advice",
        json={"project": "vinhomes-smart-city", "address": "S1.01 Vinhomes Smart City"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "google_maps_search"
    assert body["project"] == "Vinhomes Smart City"
    assert body["categories"]
    assert body["categories"][0]["map_url"].startswith("https://www.google.com/maps/search/")
    assert body["llm_advice"] == "- Ưu tiên kiểm tra map trước."


def test_amenities_advice_uses_serpapi_place_results(monkeypatch):
    def fake_get(url, params, timeout):
        query = params.get("q")
        if query == "Vinhomes Smart City, Nam Từ Liêm, Hà Nội":
            payload = {
                "place_results": {
                    "title": "Vinhomes Smart City Tây Mỗ",
                    "address": "Tây Mỗ, Hà Nội",
                    "gps_coordinates": {"latitude": 21.0062749, "longitude": 105.7371047},
                }
            }
        else:
            payload = {
                "local_results": [
                    {
                        "title": f"{query} mẫu",
                        "address": "Tây Mỗ, Hà Nội",
                        "rating": 4.5,
                        "reviews": 12,
                        "gps_coordinates": {"latitude": 21.007, "longitude": 105.738},
                    }
                ]
            }

        class FakeResponse:
            ok = True

            @staticmethod
            def json():
                return payload

        return FakeResponse()

    monkeypatch.setenv("SERPAPI_API_KEY", "serp-key")
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module.requests, "get", fake_get)
    monkeypatch.setattr(amenities_module, "generate_answer", lambda *args, **kwargs: "- SerpApi đã trả tiện ích.")

    client = TestClient(app)
    response = client.post("/amenities/advice", json={"project": "vinhomes-smart-city"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "serpapi_google_maps"
    assert body["categories"][0]["places"][0]["name"]
    assert body["categories"][0]["places"][0]["distance_m"] is not None


def test_amenities_advice_reports_google_places_key_error(monkeypatch):
    class FakeResponse:
        ok = True

        @staticmethod
        def json():
            return {"status": "REQUEST_DENIED", "error_message": "The provided API key is invalid."}

    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "bad-key")
    monkeypatch.setattr(amenities_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(amenities_module, "generate_answer", lambda *args, **kwargs: "- Places lỗi nên fallback map.")

    client = TestClient(app)
    response = client.post("/amenities/advice", json={"project": "vinhomes-smart-city"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "google_places_error"
    assert body["categories"][0]["provider_status"] == "REQUEST_DENIED"
    note_text = " ".join(body["advisory_notes"]).lower()
    assert "bản đồ" in note_text
    assert "api" not in note_text


def test_chat_asks_for_missing_fields():
    client = TestClient(app)
    response = client.post("/chat", json={"message": "định giá căn 2PN"})
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert "project" in body["missing_fields"]
    assert "area_m2" in body["missing_fields"]
    suggestions = body["data"]["retrieval_suggestions"]
    assert suggestions["nearest_projects"]
    assert suggestions["hint_text"]
    assert "dự án" in body["answer"].lower()
    assert body["plan"] == "basic"


def test_zalo_chat_endpoint_formats_missing_fields_for_zalo():
    client = TestClient(app)
    response = client.post("/zalo/chat", json={"message": "định giá căn 2PN"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert "project" in body["missing_fields"]
    assert "area_m2" in body["missing_fields"]
    assert "Mình cần thêm vài thông tin" in body["answer"]
    assert "• Dự án/khu đô thị" in body["answer"]


def test_chat_suggests_nearest_info_when_area_missing():
    client = TestClient(app)
    response = client.post("/chat", json={"message": "định giá căn hộ Vinhomes Smart City 2PN"})
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["missing_fields"] == ["area_m2"]
    suggestions = body["data"]["retrieval_suggestions"]
    assert suggestions["area_hint"]["sample_size"] > 0
    assert "vinhomes smart city" in suggestions["hint_text"].lower()
    assert "diện tích" in body["answer"].lower()
    assert "median" not in body["answer"].lower()
    assert "mẫu" not in body["answer"].lower()
    assert "triệu/m2" not in body["answer"].lower()
    assert body["plan"] == "basic"


def test_chat_greets_without_calling_valuation():
    client = TestClient(app)
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "greeting"
    assert body["missing_fields"] == []
    assert body["extracted"] == {}
    assert body["answer"]
    assert body["plan"] == "basic"
    assert body["valuation"] is None


def test_chat_help_intent_direct():
    response = chatbot_module.handle_chat(
        ChatRequest(message="bạn có thể làm gì"),
        config(),
        DB_PATH,
    )

    assert response.intent == "help"
    assert response.missing_fields == []
    assert response.valuation is None
    assert response.plan == "basic"


def test_chat_valuation_from_vietnamese_text():
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"message": "Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["valuation"]["sample_size"] > 0
    assert body["extracted"]["project"] == "vinhomes-smart-city"
    assert body["ui"]["requires_confirmation"] is True
    assert body["ui"]["actions"][0]["type"] == "manual_amenity_search"
    assert body["data"]["amenity_pending"]["cost"] == 2


def test_chat_english_valuation_returns_english(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "Estimate sale price for a 54m2 2-bedroom apartment at Vinhomes Smart City with full furniture"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["extracted"]["purpose"] == "sale"
    assert body["extracted"]["project"] == "vinhomes-smart-city"
    assert body["valuation"]["sample_size"] > 0
    assert body["answer"].startswith("For this")
    assert "cleaned public market information" in body["answer"]
    assert "sample size" not in body["answer"].lower()
    assert "Ước tính" not in body["answer"]


def test_chat_english_rent_question_returns_english(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"message": "Can you estimate the rent for a 54m2 2-bedroom apartment in Vinhomes Smart City?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["response_language"] == "en"
    assert body["intent"] == "valuation"
    assert body["extracted"]["purpose"] == "rent"
    assert body["answer"].startswith("For this")
    assert "/month" in body["answer"]
    assert "mức trung vị" not in body["answer"].lower()
    assert "dữ liệu" not in body["answer"].lower()


def test_chat_english_missing_fields_returns_english(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)
    response = client.post("/chat", json={"message": "Estimate apartment price"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert set(body["missing_fields"]) == {"project", "area_m2"}
    assert body["answer"].startswith("I need")
    assert "project" in body["answer"].lower()


def test_chat_valuation_routes_answer_through_llm_prompt(monkeypatch):
    calls = {}

    def fake_generate_answer(intent, message, context, fallback_key=None):
        calls["intent"] = intent
        calls["message"] = message
        calls["context"] = context
        calls["fallback_key"] = fallback_key
        return "- Đây là câu trả lời tự nhiên do LLM sinh từ ví dụ."

    monkeypatch.setattr(chatbot_module, "generate_answer", fake_generate_answer)

    response = chatbot_module.handle_chat(
        ChatRequest(message="Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất"),
        config(),
        DB_PATH,
    )

    assert response.answer == "- Đây là câu trả lời tự nhiên do LLM sinh từ ví dụ."
    assert calls["intent"] == "valuation"
    assert calls["fallback_key"] == "valuation"
    assert "example_answer" in calls["context"]
    assert "giá bán hợp lý nên neo" in calls["context"]["example_answer"]
    assert response.valuation is not None
    assert "sample_size" not in calls["context"]
    assert calls["context"]["plan"] == "basic"


def test_chat_trend_intent_direct():
    response = chatbot_module.handle_chat(
        ChatRequest(message="xu hướng thị trường Vinhomes Smart City căn hộ"),
        config(),
        DB_PATH,
    )

    assert response.intent == "trend"
    assert response.data is not None
    assert response.data["project"] == "Vinhomes Smart City"
    assert "windows" in response.data
    assert response.plan == "basic"


def test_chat_snapshot_intent_direct():
    response = chatbot_module.handle_chat(
        ChatRequest(message="bảng giá tham khảo Vinhomes Smart City căn hộ"),
        config(),
        DB_PATH,
    )

    assert response.intent == "snapshot"
    assert response.data is not None
    assert "reference_price_snapshots" in response.data
    assert response.plan == "basic"


def test_chat_rent_valuation_uses_structured_answer_format():
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"message": "Tôi có căn Vinhomes Smart City 54m², 2 phòng ngủ. Cho thuê được bao nhiêu?"},
    )
    assert response.status_code == 200
    body = response.json()
    answer = body["answer"]
    assert body["intent"] == "valuation"
    assert body["extracted"]["purpose"] == "rent"
    assert "giá thuê hợp lý nên neo" in answer
    assert "Độ tin cậy hiện ở mức" in answer
    assert "P10" not in answer and "P50" not in answer and "sample" not in answer.lower()
    assert "amenity_advice" not in body["data"]
    assert "bổ sung" in answer.lower()


def test_chat_buyer_asking_price_gets_purchase_advice(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={"message": "Chủ nhà chào căn 54m2 giá 5,4 tỷ ở Vinhomes Smart City, mua được không?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["missing_fields"] == []
    assert body["extracted"]["user_side"] == "buyer"
    assert body["extracted"]["asking_price_vnd"] == 5_400_000_000
    assert "5.4 tỷ" in body["answer"]
    assert "thương lượng" in body["answer"].lower()


def test_chat_quick_sale_followup_uses_prior_context(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)
    context = {
        "extracted": {
            "purpose": "sale",
            "project": "vinhomes-smart-city",
            "property_type": "apartment",
            "area_m2": 54,
            "bedrooms": 2,
            "furniture": "full",
        }
    }

    response = client.post(
        "/chat",
        json={"message": "T cần bán căn này trong một tháng, nên để giá bao nhiêu?", "context": context},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["missing_fields"] == []
    assert body["extracted"]["transaction_goal"] == "quick_transaction"
    assert "một tháng" in body["answer"].lower()
    assert "chốt nhanh" in body["answer"].lower()


def test_chat_tenant_budget_without_area_answers_fit_check(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "message": "T có ngân sách 15 triệu/tháng, muốn thuê 2PN Vinhomes Smart City để ở với con nhỏ. Có phù hợp không?"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["missing_fields"] == []
    assert body["valuation"] is None
    assert body["extracted"]["user_side"] == "tenant"
    assert body["extracted"]["budget_vnd"] == 15_000_000
    assert "ngân sách" in body["answer"].lower()
    assert "con nhỏ" in body["answer"].lower()
    assert "diện tích" in body["answer"].lower()


def test_chat_amenity_intent_returns_map_advice(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)
    monkeypatch.setattr(
        chatbot_module, "generate_answer", lambda *args, **kwargs: "- Đã tạo truy vấn tiện ích quanh khu."
    )

    client = TestClient(app)
    response = client.post("/chat", json={"message": "Tìm tiện ích xung quanh Vinhomes Smart City trên map"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "amenity"
    assert body["ui"]["requires_confirmation"] is True
    assert body["ui"]["actions"][0]["type"] == "manual_amenity_search"
    assert body["data"]["amenity_pending"]["cost"] == 2
    assert "amenity_advice" not in body["data"]


def test_chat_english_amenity_returns_english_map_advice(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)

    client = TestClient(app)
    response = client.post("/chat", json={"message": "What amenities are around Vinhomes Smart City?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "amenity"
    assert body["answer"].startswith("I can check nearby amenities")
    assert body["ui"]["actions"][0]["type"] == "manual_amenity_search"


def test_chat_continues_amenity_intent_when_user_supplies_project(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "generate_answer", lambda *args, **kwargs: "- Có thể mở map để xem tiện ích.")

    client = TestClient(app)
    first = client.post("/chat", json={"message": "gần đó có tiện ích gì không"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["intent"] == "amenity"
    assert first_body["missing_fields"] == ["project"]

    second = client.post(
        "/chat",
        json={
            "message": "Vinhomes Ocean Park",
            "context": first_body["context"],
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["intent"] == "amenity"
    assert body["missing_fields"] == []
    assert body["ui"]["requires_confirmation"] is True
    assert body["data"]["amenity_pending"]["project"] == "vinhomes-ocean-park"
    assert body["valuation"] is None


def test_chat_switches_from_pending_valuation_to_maps_tool_for_amenity_typo(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(
        chatbot_module, "generate_answer", lambda *args, **kwargs: "- Agent đã gọi tool map để xem tiện ích."
    )

    client = TestClient(app)
    first = client.post("/chat", json={"message": "Giá thuê hợp lý căn hộ Vinhomes Ocean Park 2PN"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["intent"] == "valuation"
    assert first_body["missing_fields"] == ["area_m2"]

    second = client.post(
        "/chat",
        json={
            "message": "gần đó có tiện tích gì không",
            "context": first_body["context"],
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["intent"] == "amenity"
    assert body["missing_fields"] == []
    assert body["valuation"] is None
    assert body["ui"]["actions"][0]["type"] == "manual_amenity_search"
    assert body["data"]["amenity_pending"]["project"] == "vinhomes-ocean-park"


def test_chat_amenity_followup_reuses_completed_valuation_context(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)

    client = TestClient(app)
    first = client.post("/chat", json={"message": "Định giá bán căn hộ Vinhomes Smart City 54m2 2PN full nội thất"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["intent"] == "valuation"
    assert first_body["missing_fields"] == []
    assert first_body["context"]["extracted"]["project"] == "vinhomes-smart-city"

    second = client.post(
        "/chat",
        json={
            "message": "ở gần đây có những tiện ích gì",
            "context": first_body["context"],
        },
    )

    assert second.status_code == 200
    body = second.json()
    assert body["intent"] == "amenity"
    assert body["missing_fields"] == []
    assert body["ui"]["actions"][0]["type"] == "manual_amenity_search"
    assert body["data"]["amenity_pending"]["project"] == "vinhomes-smart-city"
    assert body["valuation"] is None


def test_amenity_location_label_removes_crawler_url_noise(monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)

    advice = amenities_module.build_amenity_advice(
        AmenityAdviceRequest(
            project="vinhomes-smart-city",
            address="P. Tây Mỗ Đăng 2 ngày trước](https://batdongsan.com.vn/ban-can-ho-chung-cu-phuong-t",
            subdivision="Sapphire",
            max_places_per_category=1,
        ),
        config(),
        include_llm=False,
    )

    assert "batdongsan" not in advice.location_label
    assert "Đăng" not in advice.location_label
    assert "P. Tây Mỗ" in advice.location_label
    assert "Sapphire" in advice.location_label


def test_chat_basic_valuation_charges_one_credit_server_side(monkeypatch, tmp_path):
    db_path = tmp_path / "chat_credit.sqlite"
    shutil.copy2(DB_PATH, db_path)
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Credit User", "email": "chat-credit@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/chat",
        json={
            "message": "Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất",
            "idempotency_key": "valuation-1",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["plan"] == "basic"
    assert body["credits"]["charged"] == 1
    assert body["credits"]["balance_after"] == 4
    assert "amenity_advice" not in body["data"]
    me = client.get("/auth/me", headers=headers)
    assert me.json()["credit_balance"] == 4
    BUCKETS.clear()


def test_chat_basic_manual_amenity_charges_two_credits_once(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "DB_PATH", tmp_path / "chat_manual_map.sqlite")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Map User", "email": "map-credit@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post("/chat", json={"message": "Tìm tiện ích xung quanh Vinhomes Smart City"}, headers=headers)
    assert first.status_code == 200
    assert first.json()["ui"]["requires_confirmation"] is True

    payload = {
        "message": "Tìm tiện ích xung quanh Vinhomes Smart City",
        "action": "manual_amenity_search",
        "idempotency_key": "map-action-1",
    }
    second = client.post("/chat", json=payload, headers=headers)
    assert second.status_code == 200
    body = second.json()
    assert body["data"]["amenity_advice"]["source"] == "google_maps_search"
    assert body["credits"]["charged"] == 2
    assert body["credits"]["balance_after"] == 3

    repeated = client.post("/chat", json=payload, headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["credits"]["status"] == "already_charged"
    assert repeated.json()["credits"]["balance_after"] == 3
    assert client.get("/auth/me", headers=headers).json()["credit_balance"] == 3
    BUCKETS.clear()


def test_chat_does_not_trust_client_context_for_pro(monkeypatch, tmp_path):
    db_path = tmp_path / "chat_no_trust.sqlite"
    shutil.copy2(DB_PATH, db_path)
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Basic User", "email": "basic-context@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]

    response = client.post(
        "/chat",
        json={
            "message": "Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN",
            "context": {"plan": "agent_pro", "is_pro": True},
            "idempotency_key": "valuation-context-trust",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert body["plan"] == "basic"
    assert body["entitlements"]["is_pro"] is False
    assert "amenity_advice" not in body["data"]
    assert "news" not in body["data"]
    BUCKETS.clear()


def test_chat_agent_pro_auto_enriches_without_credit_charge(monkeypatch, tmp_path):
    db_path = tmp_path / "chat_pro.sqlite"
    shutil.copy2(DB_PATH, db_path)
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)
    monkeypatch.setattr(
        chatbot_module,
        "project_news",
        lambda *args, **kwargs: {
            "status": "ok",
            "project": "Vinhomes Smart City",
            "generated_at": datetime.now(UTC).isoformat(),
            "items": [
                {
                    "title": "Hạ tầng phía Tây Hà Nội tiếp tục được đầu tư",
                    "source": "Test News",
                    "published_text": "10/07/2026",
                    "url": "https://example.com/news",
                }
            ],
        },
    )
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Pro User", "email": "pro-chat@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_user SET pro_expires_at = ? WHERE email = ?", (expires_at, "pro-chat@example.com"))
    conn.commit()
    conn.close()

    response = client.post(
        "/chat",
        json={"message": "Định giá bán căn hộ Vinhomes Smart City 54.2m2 2PN full nội thất"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "agent_pro"
    assert body["credits"]["charged"] == 0
    assert body["data"]["amenity_advice"]["categories"]
    assert body["data"]["news"]["items"][0]["url"] == "https://example.com/news"
    assert body["data"]["outlook"]["no_appreciation_forecast"] is True
    assert body["enrichment"]["maps"]["categories"]
    BUCKETS.clear()


def test_chat_agent_pro_rent_valuation_skips_news_when_not_future_related(monkeypatch, tmp_path):
    db_path = tmp_path / "chat_pro_rent.sqlite"
    shutil.copy2(DB_PATH, db_path)
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)
    chatbot_module._VALUATION_AMENITY_CACHE.clear()
    calls = {"news": 0}

    def fake_project_news(*args, **kwargs):
        calls["news"] += 1
        return {"status": "ok", "items": [{"title": "Không nên gọi tin", "url": "https://example.com/news"}]}

    monkeypatch.setattr(chatbot_module, "project_news", fake_project_news)
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Pro Rent", "email": "pro-rent@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_user SET pro_expires_at = ? WHERE email = ?", (expires_at, "pro-rent@example.com"))
    conn.commit()
    conn.close()

    response = client.post(
        "/chat",
        json={"message": "Tôi có căn Vinhomes Smart City 54m2, 2 phòng ngủ. Cho thuê được bao nhiêu?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "agent_pro"
    assert body["intent"] == "valuation"
    assert body["valuation"]["purpose"] == "rent"
    assert calls["news"] == 0
    assert "news" not in body["data"]
    assert "outlook" not in body["data"]
    assert body["data"]["amenity_advice"]["categories"]
    BUCKETS.clear()


def test_chat_agent_pro_future_rent_question_searches_news(monkeypatch, tmp_path):
    db_path = tmp_path / "chat_pro_rent_future.sqlite"
    shutil.copy2(DB_PATH, db_path)
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)
    chatbot_module._VALUATION_AMENITY_CACHE.clear()
    calls = {"news": 0}

    def fake_project_news(*args, **kwargs):
        calls["news"] += 1
        return {
            "status": "ok",
            "project": "Vinhomes Smart City",
            "generated_at": datetime.now(UTC).isoformat(),
            "items": [
                {
                    "title": "Hạ tầng khu Đông có thay đổi mới",
                    "source": "Test News",
                    "published_text": "10/07/2026",
                    "url": "https://example.com/rent-news",
                    "impact_direction": "positive",
                    "event_status": "officially_announced",
                    "evidence_strength": "medium",
                }
            ],
        }

    monkeypatch.setattr(chatbot_module, "project_news", fake_project_news)
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Pro Rent Future", "email": "pro-rent-future@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_user SET pro_expires_at = ? WHERE email = ?", (expires_at, "pro-rent-future@example.com"))
    conn.commit()
    conn.close()

    response = client.post(
        "/chat",
        json={"message": "Căn Vinhomes Smart City 54m2 2PN cho thuê một năm nữa có tăng giá không?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "agent_pro"
    assert body["valuation"]["purpose"] == "rent"
    assert calls["news"] == 1
    assert body["data"]["news"]["items"][0]["url"] == "https://example.com/rent-news"
    assert body["data"]["outlook"]["no_appreciation_forecast"] is True
    BUCKETS.clear()


def test_chat_agent_pro_followup_reuses_prior_enrichment_without_research(monkeypatch, tmp_path):
    db_path = tmp_path / "chat_pro_followup_enrichment.sqlite"
    shutil.copy2(DB_PATH, db_path)
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(amenities_module, "_serpapi_api_key", lambda: None)
    monkeypatch.setattr(amenities_module, "_google_maps_api_key", lambda: None)
    chatbot_module._VALUATION_AMENITY_CACHE.clear()
    calls = {"maps": 0, "news": 0}
    original_build_amenity_advice = chatbot_module.build_amenity_advice

    def counting_build_amenity_advice(*args, **kwargs):
        calls["maps"] += 1
        return original_build_amenity_advice(*args, **kwargs)

    def fake_project_news(*args, **kwargs):
        calls["news"] += 1
        return {
            "status": "ok",
            "project": "Vinhomes Smart City",
            "generated_at": datetime.now(UTC).isoformat(),
            "items": [
                {
                    "title": "Hạ tầng phía Tây Hà Nội tiếp tục được đầu tư",
                    "source": "Test News",
                    "published_text": "10/07/2026",
                    "url": "https://example.com/news",
                }
            ],
        }

    monkeypatch.setattr(chatbot_module, "build_amenity_advice", counting_build_amenity_advice)
    monkeypatch.setattr(chatbot_module, "project_news", fake_project_news)
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Pro Follow", "email": "pro-follow@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_user SET pro_expires_at = ? WHERE email = ?", (expires_at, "pro-follow@example.com"))
    conn.commit()
    conn.close()

    first = client.post(
        "/chat",
        json={"message": "Định giá bán căn hộ Vinhomes Smart City 54m2 2PN full nội thất"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert calls == {"maps": 1, "news": 1}
    assert first_body["context"]["enrichment"]["maps"]
    assert first_body["context"]["enrichment"]["news"]

    second = client.post(
        "/chat",
        json={
            "message": "t nên thuê nó giá 15tr ko",
            "context": first_body["context"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert second.status_code == 200
    second_body = second.json()
    assert second_body["intent"] == "valuation"
    assert second_body["valuation"]["purpose"] == "rent"
    assert calls == {"maps": 1, "news": 1}
    assert "amenity_advice" not in second_body["data"]
    assert "news" not in second_body["data"]
    assert second_body["context"]["enrichment"]["maps"]
    assert second_body["context"]["enrichment"]["news"]
    BUCKETS.clear()


def test_chat_basic_news_question_is_not_valuation_missing(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Tháng 7 quanh Smart City có tin gì ảnh hưởng đến giá không?"})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "basic"
    assert body["intent"] == "news"
    assert body["missing_fields"] == []
    assert body["data"] == {}
    assert "Agent Pro" in body["answer"]
    assert "diện tích" not in body["answer"].lower()


def test_chat_agent_pro_news_question_searches_news_without_area(monkeypatch, tmp_path):
    db_path = tmp_path / "chat_pro_news.sqlite"
    shutil.copy2(DB_PATH, db_path)
    monkeypatch.setattr(main_module, "DB_PATH", db_path)
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    calls = {"news": 0}

    def fake_project_news(*args, **kwargs):
        calls["news"] += 1
        return {
            "status": "ok",
            "project": "Vinhomes Smart City",
            "generated_at": datetime.now(UTC).isoformat(),
            "items": [
                {
                    "title": "Điều chỉnh giao thông quanh Smart City",
                    "source": "Test News",
                    "published_text": "08/07/2026",
                    "url": "https://example.com/news",
                    "impact_direction": "positive",
                    "event_status": "officially_announced",
                    "evidence_strength": "medium",
                }
            ],
        }

    monkeypatch.setattr(chatbot_module, "project_news", fake_project_news)
    BUCKETS.clear()
    client = TestClient(app)
    registered = client.post(
        "/auth/register",
        json={"name": "Pro News", "email": "pro-news@example.com", "password": "secret123"},
    )
    token = registered.json()["access_token"]
    expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE app_user SET pro_expires_at = ? WHERE email = ?", (expires_at, "pro-news@example.com"))
    conn.commit()
    conn.close()

    response = client.post(
        "/chat",
        json={"message": "Tháng 7 quanh Smart City có tin gì ảnh hưởng đến giá không?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "agent_pro"
    assert body["intent"] == "news"
    assert body["missing_fields"] == []
    assert calls["news"] == 1
    assert body["data"]["news"]["items"][0]["url"] == "https://example.com/news"
    assert body["data"]["outlook"]["no_appreciation_forecast"] is True
    BUCKETS.clear()


def test_chat_recent_price_trend_is_not_amenity(monkeypatch):
    monkeypatch.setenv("VALUATION_LLM_ENABLED", "0")
    client = TestClient(app)

    response = client.post("/chat", json={"message": "Ba tháng gần đây giá Smart City tăng hay giảm?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "trend"
    assert "windows" in body["data"]
    assert "amenity_pending" not in body["data"]
