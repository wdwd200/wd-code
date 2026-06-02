from wdcode.core.response_router import route_assistant_message


def test_response_router_routes_final_answer_without_tool_calls():
    assistant_message = {
        "role": "assistant",
        "content": "done",
    }

    route = route_assistant_message(assistant_message)

    assert route.is_final is True
    assert route.content == "done"
    assert route.tool_calls == ()
    assert route.raw_message is assistant_message


def test_response_router_normalizes_empty_content_for_final_answer():
    route = route_assistant_message({"role": "assistant", "content": None})

    assert route.is_final is True
    assert route.content == ""
    assert route.tool_calls == ()


def test_response_router_routes_tool_calls_as_stable_tuple():
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "list_files",
            "arguments": "{}",
        },
    }
    assistant_message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [tool_call],
    }

    route = route_assistant_message(assistant_message)

    assert route.is_final is False
    assert route.content == ""
    assert route.tool_calls == (tool_call,)
    assert route.raw_message is assistant_message
