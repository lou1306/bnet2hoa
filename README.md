# BNET2HOA: Boolean network into HOA format

This tool takes as input a Boolean network expressed in the `.bnet` format
(as used, e.g., by `pyboolnet` and `BNetToPrime`). Then, it builds a HOA
automaton (https://adl.github.io/hoaf/) that captures the network's
state-transition graph under a hybrid (aka generalised asynchronous) update
paradigm. The automaton takes as input *n* atomic propositions, one for each
variable in the Boolean network. If the *i*-th proposition is set to true,
the next state will update the *i*-th variable. Therefore:

* Setting every AP true at every step results in the synchronous updating scheme.
* Setting exactly one AP true at every step results in the "traditional" asynchronous updating scheme.

## Options

* `--allow-stutter`: Treat the input where all APs are false as a no-op (no update function is applied).
Since BNs usually are not allowed to stutter, by default the tool treats this input as a synchronous update.

## Dependencies

This tool depends on [BNetToPrime](https://github.com/xstreck1/BNetToPrime).
