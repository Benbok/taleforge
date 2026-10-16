"""Bounded WebSocket waits used by asynchronous gateway tests."""

import pytest

from tests.test_ws import connect, setup, wait_message_result


def test_wait_message_result_returns_rejection_for_its_client_id(client, admin):
    campaign, player, _ = setup(client, admin)

    with connect(client, player, campaign["id"]) as (ws, _):
        ws.send_json(
            {
                "type": "message.send",
                "payload": {"kind": "action", "text": "Открываю дверь", "client_id": "reject-me"},
            }
        )
        event = wait_message_result(ws, client_id="reject-me", timeout_s=0.5)

    assert event["type"] == "message.rejected"
    assert event["payload"]["client_id"] == "reject-me"


def test_wait_message_result_returns_successful_publication(client, admin):
    campaign, player, _ = setup(client, admin, master={"type": "owner"})
    client.post(f"/api/campaigns/{campaign['id']}/session/start", headers=admin)

    with connect(client, player, campaign["id"]) as (ws, _):
        ws.send_json(
            {
                "type": "message.send",
                "payload": {"kind": "ooc", "text": "Проверка связи", "client_id": "publish-me"},
            }
        )
        event = wait_message_result(ws, client_id="publish-me", timeout_s=0.5)

    assert event["type"] == "message.new"
    assert event["payload"]["content"] == "Проверка связи"


def test_wait_message_result_reports_received_event_types_on_timeout(client, admin):
    campaign, player, _ = setup(client, admin)

    with connect(client, player, campaign["id"]) as (ws, _):
        with pytest.raises(TimeoutError, match="received event types") as exc:
            wait_message_result(ws, client_id="never", timeout_s=0.01)

    assert "state.snapshot" not in str(exc.value)


def test_wait_message_result_does_not_consume_unrelated_broadcast(client, admin):
    campaign, player, other = setup(client, admin)

    with connect(client, player, campaign["id"]) as (ws, _):
        with connect(client, other, campaign["id"]):
            with pytest.raises(TimeoutError, match="presence.changed"):
                wait_message_result(ws, client_id="no-message", timeout_s=0.05)
