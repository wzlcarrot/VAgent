"""ReAct 重复调用防护（DuplicateCallGuard）单测。"""
from app.agents.react_guard import DuplicateCallGuard, normalize_args


def test_normalize_args_stable_key_order():
    a = normalize_args({"question": "x", "top_k": 5})
    b = normalize_args({"top_k": 5, "question": "x"})
    assert a == b


def test_normalize_args_strips_string_whitespace():
    assert normalize_args({"question": " 讲了什么 "}) == normalize_args({"question": "讲了什么"})


def test_normalize_args_handles_empty_and_nested():
    assert normalize_args(None) == "{}"
    assert normalize_args({}) == "{}"
    assert normalize_args({"q": {"b": 1, "a": 2}}) == normalize_args({"q": {"a": 2, "b": 1}})


def test_normalize_args_survives_unserializable():
    class Weird:
        pass

    out = normalize_args({"obj": Weird()})
    assert out  # 不抛异常，退化为 repr


def test_guard_flags_repeat_call():
    guard = DuplicateCallGuard()
    assert guard.is_duplicate("search", {"question": "x", "top_k": 5}) is False
    assert guard.is_duplicate("search", {"question": "x", "top_k": 5}) is True
    assert len(guard) == 1


def test_guard_allows_different_args_or_tool():
    guard = DuplicateCallGuard()
    assert guard.is_duplicate("search", {"question": "x"}) is False
    assert guard.is_duplicate("search", {"question": "y"}) is False
    assert guard.is_duplicate("other", {"question": "x"}) is False
    assert len(guard) == 3


def test_guard_trailing_space_is_same_call():
    guard = DuplicateCallGuard()
    assert guard.is_duplicate("search", {"question": "x"}) is False
    assert guard.is_duplicate("search", {"question": "x "}) is True
