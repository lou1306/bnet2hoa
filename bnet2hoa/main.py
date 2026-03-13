import argparse
import os
import sys
import tempfile
from importlib import resources
from itertools import chain, combinations
from subprocess import run
from typing import Callable
from shutil import which


from msgspec import json
from sympy.utilities.autowrap import autowrap

from .bnet import bnet2sympy


def get_eval_int_fn_bnet(bnet_file: str) -> tuple[Callable[[int], int], tuple]:
    functions, symbols = bnet2sympy(bnet_file)
    n = len(symbols)
    compiled = {
        target: autowrap(factors, args=symbols, backend="cython")
        for target, factors in functions.items()}

    def eval_int(state: int) -> int:
        new_state = state
        valuation = [bool((state >> (n - j - 1)) & 1) for j in range(n)]
        for i, ap in enumerate(symbols):
            if compiled[ap](*valuation):
                new_state |= (1 << (n - i - 1))
            else:
                new_state &= ~(1 << (n - i - 1))
        return new_state
    return eval_int, symbols


def get_eval_state_fn(primes: dict) -> Callable[[dict], dict]:
    aps = set(primes.keys())

    def eval_state(state: dict) -> dict:
        new_state = {**state}
        for ap in aps:
            primes_neg, primes_true = primes[ap]
            for pr in primes_neg:
                if all(bool(pr[lit]) == state[lit] for lit in pr):
                    new_state[ap] = False
                    break
            else:
                for pr in primes_true:
                    if all(bool(pr[lit]) == state[lit] for lit in pr):
                        new_state[ap] = True
                        break
                else:
                    raise ValueError("State does not evaluate")
        return new_state
    return eval_state


def get_eval_int_fn(primes: dict) -> Callable[[int], int]:
    aps = tuple(primes.keys())
    ap_index = {ap: i for i, ap in enumerate(aps)}

    def eval_int(state: int) -> int:
        ap_size = len(primes)
        new_state = state
        for ap in aps:
            primes_neg, primes_true = primes[ap]
            for pr in primes_neg:
                if all(pr[lit] == (state >> (ap_size - ap_index[lit] - 1)) & 1 for lit in pr):  # noqa: E501
                    new_state &= ~(1 << (ap_size - ap_index[ap] - 1))
                    break
            else:
                for pr in primes_true:
                    if all(pr[lit] == (state >> (ap_size - ap_index[lit] - 1)) & 1 for lit in pr):  # noqa: E501
                        new_state |= (1 << (ap_size - ap_index[ap] - 1))
                        break
                else:
                    raise ValueError("State does not evaluate")
        return new_state
    return eval_int


def int_to_state(state: int, aps: list[str]) -> dict:
    return {
        ap: bool((state >> (len(aps) - i - 1)) & 1)
        for i, ap in enumerate(aps)}


def int_to_bin(state: int, aps: list[str]) -> str:
    return "".join(
        str((state >> (len(aps) - i - 1)) & 1)
        for i in range(len(aps)))


def state_to_int(state: dict, aps: list[str]) -> int:
    result = 0
    for i, ap in enumerate(reversed(aps)):
        if state[ap]:
            result |= (1 << i)
    return result


def primes_setup(primes: dict):
    def fn():
        eval_int = get_eval_int_fn(primes)
        all_aps = list(primes.keys())
        ap_index = {ap: i for i, ap in enumerate(all_aps)}
        return eval_int, ap_index
    return fn


def bnet_setup(eval_int, symbols):
    def fn():
        return eval_int, {s.name: i for i, s in enumerate(symbols)}
    return fn


def get_worker_fn(setup, allow_stuttering: bool = False) -> Callable[[int], dict]:  # noqa: E501
    """Return a function that computes the transition relation for a state.

    The inner function encodes transitions in a DNF, DIMACS-like format.
    trel[next_state] is a list of tuples of integers. Each tuple is a clause,
    and the elements of the tuple are the conjuncts of the clause.
    "i" is a literal referring to the (i+1)th variable.
    "-i" is a negated literal.
    "0" is the true constant.

    Args:
        primes (dict): Prime implicant mapping (As given by BNetToPrime)
        allow_stuttering (bool, optional): _description_. Defaults to False.

    Returns:
        Callable[[int], dict]: A worker function.
    """
    eval_int, ap_index = setup()

    def powerset(iterable):
        s = list(iterable)
        return chain.from_iterable(combinations(s, r) for r in range(len(s)+1))

    def clause(true_indexes: tuple[int], all_indexes: tuple[int]) -> str:
        return tuple(i+1 if i in true_indexes else -(i+1) for i in all_indexes)

    def worker(state: int) -> dict:
        trel = {}

        sync_next = eval_int(state)

        # Bits that change or stay the same in sync_next
        differences = state ^ sync_next
        same = ~differences
        diff_indexes = [
            i for i in range(len(ap_index))
            if (differences >> (len(ap_index) - i - 1)) & 1]

        # When all bits change, the only possible next state is sync_next
        trel[sync_next] = [clause(diff_indexes, diff_indexes)]

        if state == sync_next:
            # This is an attractor state
            trel[state] = [(0,)]
            return trel

        if same != 0:
            # If no bits are selected from diff_indexes, state does not change
            trel[state] = [clause((), diff_indexes)]
        elif not allow_stuttering:
            # If stuttering was not allowed, selecting no update
            # is the same as selecting a synchronous update
            trel[sync_next].append(clause((), ap_index.values()))

        for indexes in powerset(diff_indexes):
            if len(indexes) == 0 or len(indexes) == len(diff_indexes):
                continue
            mask = 0
            for index in indexes:
                mask |= (1 << (len(ap_index) - index - 1))
            cur_next = (sync_next & ~mask) | (state & mask)
            guard = clause(indexes, diff_indexes)
            if cur_next not in trel:
                trel[cur_next] = [guard]
            else:
                trel[cur_next].append(guard)
        return trel
    return worker


def get_primes(bnet_file: str, timeout: float | None = None) -> dict:
    bnet = which("BNetToPrime")
    if bnet is None:
        bnet_path = [
            "bnet2hoa", "data",
            "BNetToPrime-macos" if sys.platform == "darwin" else "BNetToPrime"]
        if resources.is_resource(*bnet_path) and sys.platform != "win32":
            with resources.path(*bnet_path) as bnet_path:
                bnet = bnet_path
        else:
            print("BNetToPrime binary not found.")
            sys.exit(1)
    with tempfile.NamedTemporaryFile(suffix=".bnet", delete=False) as tmp:
        tmp.close()
        run(
            [str(bnet), bnet_file, tmp.name],
            stdout=sys.stderr, check=True, timeout=timeout)  # noqa: E501
        print(file=sys.stderr)
        with open(tmp.name, "rb") as tmp:
            out = tmp.read().decode("utf-8").strip()
        os.unlink(tmp.name)
    primes = json.decode(out)
    return primes


def main():
    parser = argparse.ArgumentParser(
        prog="bnet2hoa",
        description="Generate the state space of a Boolean network in HOA format")  # noqa: E501
    parser.add_argument("bnet_file", help="path to a .bnet file")
    parser.add_argument(
        "--allow-stuttering", action="store_true",
        help="allow stuttering transitions (default: False)")
    parser.add_argument(
        "--primes", action="store_true",
        help="use prime implicants only (default: False)")
    parser.add_argument(
        '--start', type=int, action='append', default=[],
        help=(
            "specify one or more start state. "
            "Use -1 to omit the 'Start:' header entirely. "
            "Notice that this results in an empty automaton per the HOA specification. "  # noqa: E501
            "May be specified multiple times (default: all states)"))
    parser.add_argument(
        '--state', type=int, action='append', default=[],
        help=(
            "state to be included in the output. "
            "Use -1 to print only the header. "
            "May be specified multiple times (default: all states)"))
    args = parser.parse_args()

    if args.primes:
        primes = get_primes(args.bnet_file)
        aps = tuple(primes.keys())
        setup_fn = primes_setup(primes)
    else:
        eval_int, symbols = get_eval_int_fn_bnet(args.bnet_file)
        aps = tuple(x.name for x in symbols)
        setup_fn = bnet_setup(eval_int, symbols)

    worker = get_worker_fn(setup_fn, allow_stuttering=args.allow_stuttering)  # noqa: E501

    num_states = 2 ** len(aps)
    print("HOA: v1")
    print("AP:", len(aps), " ".join(f'"{ap}"' for ap in aps))
    print("States:", num_states)
    if -1 not in args.start:
        start_states = args.start if args.start else range(num_states)
        for i in start_states:
            if i < 0 or i >= num_states:
                print(
                    f"[WARNING] Skipping invalid start state: {i}",
                    file=sys.stderr)
                continue
            print("Start:", i)
    print("Acceptance: 0 t")
    print("--BODY--")
    if -1 in args.state:
        print("--END--")
        return

    states = args.state if args.state else range(num_states)
    if len(states) > 2*24:
        print(
            f"[WARNING] Automaton may have up to {len(states):.2e} states.",
            file=sys.stderr)

    def fmt_variable(i: int) -> str:
        if i == 0:
            return "t"
        return f"{i-1}" if i > 0 else f"!{(-i-1)}"

    for state in states:
        if state < 0 or state >= num_states:
            print(f"[WARNING] Skipping invalid state: {state}", file=sys.stderr)  # noqa: E501
            continue
        tr = worker(state)
        print(f'State: {state} "{int_to_bin(state, aps)}"')
        for next_state, guard_dnf in tr.items():
            guard = "|".join(
                "&".join(fmt_variable(i) for i in guard_clause)
                for guard_clause in guard_dnf)
            print(f'[{guard}] {next_state}')
    print("--END--")


if __name__ == "__main__":
    main()
