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
    aps = list(primes.keys())
    ap_index = {ap: i for i, ap in enumerate(aps)}

    def eval_int(state: int) -> int:
        ap_size = len(primes)
        new_state = (2 ** ap_size - 1)
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


def get_worker_fn(primes: dict, allow_stuttering: bool = False) -> Callable[[int], dict]:  # noqa: E501
    eval_int = get_eval_int_fn(primes)
    all_aps = list(primes.keys())
    ap_index = {ap: i for i, ap in enumerate(all_aps)}

    def powerset(iterable):
        s = list(iterable)
        return chain.from_iterable(combinations(s, r) for r in range(len(s)+1))

    def worker(state: int) -> dict:
        trel = {}

        sync_next = eval_int(state)

        # Bits that change or stay the same in sync_next
        differences = state ^ sync_next
        same = ~differences
        diff_indexes = [
            i for i in range(len(all_aps))
            if (differences >> (len(all_aps) - i - 1)) & 1]

        trel[sync_next] = "&".join(f"{i}" for i in diff_indexes)  # noqa: E501

        if state == sync_next:
            # This is an attractor state
            trel[state] = "t"
            return trel

        if same != 0:
            # If no bits are selected from diff_indexes, state does not change
            trel[state] = "&".join(f"!{i}" for i in diff_indexes)
        elif not allow_stuttering:
            # If stuttering was not allowed, selecting no update
            # is the same as selecting a synchronous update
            trel[sync_next] = "&".join(f"!{i}" for i in ap_index.values())

        for indexes in powerset(diff_indexes):
            if len(indexes) == 0 or len(indexes) == len(diff_indexes):
                continue
            mask = 0
            for index in indexes:
                mask |= (1 << (len(all_aps) - index - 1))
            cur_next = (sync_next & ~mask) | (state & mask)

            guard = "&".join(str(i) if i in indexes else f"!{i}" for i in diff_indexes)  # noqa: E501
            if cur_next not in trel:
                trel[cur_next] = guard
            else:
                trel[cur_next] += " | " + guard
        return trel
    return worker


def get_primes(bnet_file: str) -> dict:
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
        run([str(bnet), bnet_file, tmp.name], stdout=sys.stderr, check=True)  # noqa: E501
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
    primes = get_primes(args.bnet_file)
    aps = tuple(primes.keys())
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

    worker = get_worker_fn(primes, allow_stuttering=args.allow_stuttering)
    states = args.state if args.state else range(num_states)
    if len(states) > 2*24:
        print(
            f"[WARNING] Automaton may have up to {len(states):.2e} states.",
            file=sys.stderr)

    for state in states:
        if state < 0 or state >= num_states:
            print(f"[WARNING] Skipping invalid state: {state}", file=sys.stderr)
            continue
        tr = worker(state)
        print(f'State: {state} "{int_to_bin(state, aps)}"')
        for next_state, guard in tr.items():
            print(f'[{guard}] {next_state}')
    print("--END--")

if __name__ == "__main__":
    main()
