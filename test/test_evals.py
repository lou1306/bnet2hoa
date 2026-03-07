from hypothesis import given
from hypothesis import strategies as st

from bnet2hoa.main import (get_eval_int_fn, get_eval_state_fn, int_to_state,
                           state_to_int)

primes = {
    'v1': [[{'v5': 0}, {'v4': 0}], [{'v4': 1, 'v5': 1}]],
    'v2': [[{'v1': 0}], [{'v1': 1}]],
    'v3': [[{'v2': 0}], [{'v2': 1}]],
    'v4': [[{'v3': 0}], [{'v3': 1}]],
    'v5': [[{'v1': 0, 'v7': 0}], [{'v7': 1}, {'v1': 1}]],
    'v6': [[{'v2': 0, 'v5': 0}], [{'v5': 1}, {'v2': 1}]],
    'v7': [[{'v6': 0}], [{'v6': 1}]]}


@given(st.integers(min_value=0, max_value=127))
def test_int_to_state_and_back(s):
    aps = set(primes.keys())
    state = int_to_state(s, list(aps))
    new_s = state_to_int(state, list(aps))
    assert s == new_s


@given(st.integers(min_value=0, max_value=127))
def test_eval_int_state_commute(s):
    eval_int = get_eval_int_fn(primes)
    eval_state = get_eval_state_fn(primes)
    aps = list(primes.keys())
    state = int_to_state(s, aps)
    eval_state_result = eval_state(state)
    eval_int_result = eval_int(s)
    assert eval_state_result == int_to_state(eval_int_result, aps)
    assert eval_int_result == state_to_int(eval_state_result, aps)

@given(st.integers(min_value=0, max_value=127))
def test_eval_int_deterministic(s):
    eval_int = get_eval_int_fn(primes)
    result1 = eval_int(s)
    result2 = eval_int(s)
    assert result1 == result2
