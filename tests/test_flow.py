from datetime import date

from tests.conftest import PASSWORD


def _employee_id(client, h, last_name):
    rows = client.get("/api/v1/refs/employees", params={"q": last_name}, headers=h).json()
    return rows[0]["id"]


def _free_items(client, h, n=2):
    items = client.get("/api/v1/items", params={"status": "in_stock", "kind": "computer"}, headers=h).json()
    return [i["id"] for i in items[:n]]


def test_auth_required(client):
    assert client.get("/api/v1/items").status_code == 401
    r = client.get("/items", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_bad_login(client):
    r = client.post("/api/v1/auth/token", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_role_permissions(client, tokens):
    # пользователь не видит справочники и не создаёт позиции
    assert client.get("/api/v1/refs/counterparties", headers=tokens["ivanov"]).status_code == 403
    item = {"kind": "furniture", "name": "Шкаф", "organization_id": 1}
    assert client.post("/api/v1/items", json=item, headers=tokens["ivanov"]).status_code == 403
    # руководитель только просматривает
    assert client.post("/api/v1/items", json=item, headers=tokens["head"]).status_code == 403
    assert client.get("/api/v1/refs/counterparties", headers=tokens["head"]).status_code == 200
    # пользователями управляет только администратор
    assert client.get("/api/v1/users", headers=tokens["manager"]).status_code == 403
    assert client.get("/api/v1/users", headers=tokens["admin"]).status_code == 200


def test_inn_validation(client, tokens):
    r = client.post("/api/v1/refs/counterparties", json={"name": "ООО Тест", "inn": "7725181418"},
                    headers=tokens["manager"])
    assert r.status_code == 422
    r = client.post("/api/v1/refs/counterparties", json={"name": "ООО Тест", "inn": "7707083893"},
                    headers=tokens["manager"])
    assert r.status_code == 201


def test_full_waybill_flow(client, tokens):
    m, h = tokens["manager"], tokens["head"]
    mol = _employee_id(client, m, "Кузнецова")
    ivanov = _employee_id(client, m, "Иванов")
    items = _free_items(client, m)

    r = client.post("/api/v1/waybills", headers=m, json={
        "type": "issue", "date": date.today().isoformat(), "organization_id": 1,
        "sender_id": mol, "receiver_id": ivanov, "item_ids": items, "basis": "Заявка № 1",
    })
    assert r.status_code == 201, r.text
    wb = r.json()
    assert wb["status"] == "draft" and len(wb["lines"]) == 2

    # позицию нельзя включить во вторую накладную, пока первая не завершена
    r = client.post("/api/v1/waybills", headers=m, json={
        "type": "issue", "date": date.today().isoformat(), "organization_id": 1,
        "sender_id": mol, "receiver_id": ivanov, "item_ids": items[:1],
    })
    assert r.status_code == 400

    # руководитель не видит и не может подписать накладную раньше МОЛ, подпись без пароля не принимается
    assert client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=h).status_code == 404
    assert client.post(f"/api/v1/waybills/{wb['id']}/sign", json={}, headers=m).status_code == 400

    r = client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=m)
    assert r.json()["status"] == "manager_signed"
    r = client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=h)
    assert r.json()["status"] == "approved"

    item = client.get(f"/api/v1/items/{items[0]}", headers=m).json()
    assert item["status"] == "issued" and item["holder_id"] == ivanov

    # получатель видит своё имущество и подтверждает получение; чужой пользователь накладную не видит
    mine = client.get("/api/v1/items", headers=tokens["ivanov"]).json()
    assert {i["id"] for i in mine} >= set(items)
    assert client.get(f"/api/v1/waybills/{wb['id']}", headers=tokens["smirnova"]).status_code == 403
    r = client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=tokens["ivanov"])
    assert r.json()["status"] == "received"
    assert [s["signer_role"] for s in r.json()["signatures"]] == ["manager", "head", "receiver"]

    # выданную позицию нельзя списать без возврата
    r = client.post(f"/api/v1/items/{items[0]}/status", json={"status": "written_off", "reason": "акт"}, headers=m)
    assert r.status_code == 400

    # возврат на склад
    r = client.post("/api/v1/waybills", headers=m, json={
        "type": "return", "date": date.today().isoformat(), "organization_id": 1,
        "sender_id": ivanov, "receiver_id": mol, "item_ids": items[:1],
    })
    assert r.status_code == 201, r.text
    ret = r.json()
    client.post(f"/api/v1/waybills/{ret['id']}/sign", json={"password": PASSWORD}, headers=m)
    client.post(f"/api/v1/waybills/{ret['id']}/sign", json={"password": PASSWORD}, headers=h)
    item = client.get(f"/api/v1/items/{items[0]}", headers=m).json()
    assert item["status"] == "in_stock" and item["holder_id"] is None


def test_web_pages_render(client):
    r = client.post("/login", data={"username": "manager", "password": PASSWORD}, follow_redirects=False)
    assert r.status_code == 303
    for url in ("/", "/items", "/items?kind=license", "/items/new", "/items/1", "/waybills", "/waybills/new",
                "/waybills/new?type=return", "/waybills/1", "/waybills/1/print", "/refs/contracts",
                "/refs/employees/new", "/refs/organizations/1/edit"):
        assert client.get(url).status_code == 200, url
    client.get("/logout")
    client.post("/login", data={"username": "admin", "password": "admin-test-pass"})
    for url in ("/users", "/users/new", "/audit"):
        assert client.get(url).status_code == 200, url
    client.get("/logout")
