from mini_go_server.events import EventBus


def test_event_bus_keeps_history_and_notifies_subscribers() -> None:
    events = EventBus(history_limit=2)
    subscriber = events.subscribe()

    first = events.publish("first", value=1)
    second = events.publish("second", value=2)
    third = events.publish("third", value=3)

    assert [event.type for event in events.history()] == ["second", "third"]
    assert subscriber.get_nowait() == first  # type: ignore[attr-defined]
    assert subscriber.get_nowait() == second  # type: ignore[attr-defined]
    assert subscriber.get_nowait() == third  # type: ignore[attr-defined]

    events.unsubscribe(subscriber)
