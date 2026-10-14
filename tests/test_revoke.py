from datetime import date

from tests.conftest import PASSWORD
from tests.test_flow import _employee_id, _free_items

REASON = {"reason": "ошибка в составе"}


def _approved_waybill(client, tokens, items, type_="issue", sender="Кузнецова", receiver="Иванов"):
    m, h = tokens["manager"], tokens["head"]
    r = client.post("/api/v1/waybills", headers=m, json={
        "type": type_, "date": date.today().isoformat(), "organization_id": 1,
        "sender_id": _employee_id(client, m, sender), "receiver_id": _employee_id(client, m, receiver),
        "item_ids": items,
    })
    assert r.status_code == 201, r.text
    wb = r.json()
    for headers in (m, h):
        r = client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=headers)
        assert r.status_code == 200, r.text
    return r.json()


def _revoke(client, headers, wb, role, body=REASON):
    sig = next(s for s in wb["signatures"] if s["signer_role"] == role)
    return client.post(f"/api/v1/waybills/{wb['id']}/signatures/{sig['id']}/revoke", json=body, headers=headers)


def _item(client, tokens, item_id):
    return client.get(f"/api/v1/items/{item_id}", headers=tokens["manager"]).json()


def test_signers_revoke_in_reverse_order_then_delete(client, tokens):
    m, h, ivanov = tokens["manager"], tokens["head"], tokens["ivanov"]
    items = _free_items(client, m, 1)
    wb = _approved_waybill(client, tokens, items)
    r = client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=ivanov)
    wb = r.json()
    assert wb["status"] == "received"

    # отменить можно только свою последнюю подпись и только с причиной
    assert _revoke(client, m, wb, "manager").status_code == 403
    assert _revoke(client, h, wb, "head").status_code == 403
    assert _revoke(client, ivanov, wb, "receiver", {"reason": ""}).status_code == 422

    wb = _revoke(client, ivanov, wb, "receiver").json()
    assert wb["status"] == "approved"
    wb = _revoke(client, h, wb, "head").json()
    assert wb["status"] == "manager_signed"
    item = _item(client, tokens, items[0])
    assert item["status"] == "in_stock" and item["holder_id"] is None

    # пока есть подписи, менеджер накладную не удаляет
    assert client.delete(f"/api/v1/waybills/{wb['id']}", headers=m).status_code == 400
    wb = _revoke(client, m, wb, "manager").json()
    assert wb["status"] == "draft" and wb["signatures"] == []
    assert client.delete(f"/api/v1/waybills/{wb['id']}", headers=m).status_code == 204

    log = client.get("/audit", headers=tokens["admin"])
    assert log.status_code == 200


def test_admin_revokes_any_signature_and_deletes(client, tokens):
    admin = tokens["admin"]
    items = _free_items(client, tokens["manager"], 1)
    wb = _approved_waybill(client, tokens, items)
    assert _item(client, tokens, items[0])["status"] == "issued"

    # отмена подписи МОЛ отменяет и подпись руководителя, имущество возвращается на склад
    wb = _revoke(client, admin, wb, "manager").json()
    assert wb["status"] == "draft" and wb["signatures"] == []
    assert _item(client, tokens, items[0])["status"] == "in_stock"

    for headers in (tokens["manager"], tokens["head"]):
        wb = client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=headers).json()
    assert wb["status"] == "approved"

    # менеджер подписанную накладную не удаляет; администратор — только с причиной
    assert client.delete(f"/api/v1/waybills/{wb['id']}", headers=tokens["manager"]).status_code == 400
    assert client.delete(f"/api/v1/waybills/{wb['id']}", headers=admin).status_code == 400
    r = client.delete(f"/api/v1/waybills/{wb['id']}", params={"reason": "дубликат"}, headers=admin)
    assert r.status_code == 204
    assert client.get(f"/api/v1/waybills/{wb['id']}", headers=admin).status_code == 404
    item = _item(client, tokens, items[0])
    assert item["status"] == "in_stock" and item["holder_id"] is None


def test_revoke_blocked_after_later_movement(client, tokens):
    admin = tokens["admin"]
    items = _free_items(client, tokens["manager"], 1)
    issue = _approved_waybill(client, tokens, items)
    back = _approved_waybill(client, tokens, items, type_="return", sender="Иванов", receiver="Кузнецова")
    assert _item(client, tokens, items[0])["status"] == "in_stock"

    # имущество уже возвращено следующей накладной — утверждение выдачи отменить нельзя
    assert _revoke(client, admin, issue, "head").status_code == 400
    assert client.delete(f"/api/v1/waybills/{issue['id']}", params={"reason": "x"}, headers=admin).status_code == 400

    # отмена в обратном порядке допустима
    assert _revoke(client, admin, back, "head").json()["status"] == "manager_signed"
    item = _item(client, tokens, items[0])
    assert item["status"] == "issued"
    assert _revoke(client, admin, issue, "head").status_code == 400  # возврат ещё действует (подписан МОЛ)
    client.delete(f"/api/v1/waybills/{back['id']}", params={"reason": "x"}, headers=admin)
    assert _revoke(client, admin, issue, "head").json()["status"] == "manager_signed"
    assert _item(client, tokens, items[0])["status"] == "in_stock"
    client.delete(f"/api/v1/waybills/{issue['id']}", params={"reason": "x"}, headers=admin)


def test_head_sees_waybill_only_after_manager_signature(client, tokens):
    m, h = tokens["manager"], tokens["head"]
    items = _free_items(client, m, 1)
    wb = client.post("/api/v1/waybills", headers=m, json={
        "type": "issue", "date": date.today().isoformat(), "organization_id": 1,
        "sender_id": _employee_id(client, m, "Кузнецова"), "receiver_id": _employee_id(client, m, "Иванов"),
        "item_ids": items,
    }).json()
    assert "id" in wb, wb

    def visible():
        listed = wb["id"] in {w["id"] for w in client.get("/api/v1/waybills", headers=h).json()}
        opened = client.get(f"/api/v1/waybills/{wb['id']}", headers=h).status_code
        history = f'/waybills/{wb["id"]}"' in client.get(f"/items/{items[0]}", headers=h).text
        return listed, opened, history

    assert visible() == (False, 404, False)
    assert client.get(f"/api/v1/waybills/{wb['id']}", headers=m).status_code == 200

    client.post(f"/api/v1/waybills/{wb['id']}/sign", json={"password": PASSWORD}, headers=m)
    assert visible() == (True, 200, True)

    # после отмены подписи МОЛ накладная снова скрыта
    _revoke(client, m, client.get(f"/api/v1/waybills/{wb['id']}", headers=m).json(), "manager")
    assert visible() == (False, 404, False)
    client.delete(f"/api/v1/waybills/{wb['id']}", headers=m)
