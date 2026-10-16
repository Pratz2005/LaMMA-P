"""Repair a Safety-DAG violation by asking the model for the missing :init atoms.

scripts/dag_inject.py writes the missing fact in directly: the DAG derived the
ordering constraint from the knowledge graph, so it already holds the exact
ground atom the problem file lacks, and writing it cannot fail. This module is
the other arm of that comparison - same violation, same run, but the atom is
produced by the language model instead of by the injector.

    detect -> PROMPT THE MODEL -> screen the reply -> inject -> replan -> re-check

The model is asked for facts. Not for a plan, not for a repair strategy, not for
a rewritten problem file - only for the ground atoms that belong in (:init ...)
and are not there. What comes back is screened in three passes before any of it
reaches the file:

  1. syntax      one balanced (predicate arg ...) per line; prose and fences are
                 discarded rather than parsed.
  2. vocabulary  the predicate must exist in the domain and every argument must
                 be an object the problem file declares. This one matters more
                 than it looks: (isClosed Drawer_1) is the property stage's
                 spelling of the same fact, and Fast Downward drops an unknown
                 predicate without an error - so an unscreened reply can "repair"
                 a file while changing nothing about what it means.
  3. truth       the atom must be one the knowledge graph asserts. The graph is
                 read from the simulator's own metadata, so this is the pass that
                 stops the model from clearing the violation by asserting
                 something false: (object-open drawer_1) satisfies the check just
                 as well as (object-close drawer_1) and is a lie about the world.

The model proposes, the graph disposes. Screening never supplies an atom the
model did not produce, so a model that stays silent - or that answers in the
wrong vocabulary - yields no repair and the violation survives. That is the
result of the experiment, not a failure to be papered over with a fallback.

Standalone:

    python scripts/dag_llm_init.py runs_3/FP201_t0_easy_20260902-192327 --print-prompt
    python scripts/dag_llm_init.py runs_3/FP201_t0_easy_20260902-192327
"""
import argparse
import json
import os
import re
import sys
from collections import namedtuple

sys.path.append(".")
from scripts.safety_dag import derive_dag, check_plan, load_plan, load_problem

# Overridable so a run can pin the domain it was designed against without
# editing the working tree. Default unchanged.
DOMAIN = os.environ.get("KGLAMP_DOMAIN", "resources/robot3.pddl")

# graph fact -> the domain predicate that states it in (:init ...). Only the
# flags the domain can express are listed; a graph fact with no PDDL spelling
# is not something a repair can restore, so it is not offered to the model.
CAPABILITY_PREDICATE = {"openable": "openable", "pickupable": "pickupable",
                        "sliceable": "sliceable", "toggleable": "toggleable"}
STATE_PREDICATE = {("isOpen", True): "object-open",
                   ("isOpen", False): "object-close",
                   ("isToggled", True): "switch-on",
                   ("isToggled", False): "switch-off",
                   ("isSliced", True): "sliced",
                   ("isBroken", True): "break"}

Screened = namedtuple("Screened", "accepted rejected redundant")
Repair = namedtuple("Repair",
                    "prompt raw atoms screened dag_atoms agreed missed extra "
                    "model base_url attempts transcript")
# Older call sites construct a Repair without the last two; one attempt, no
# transcript, is exactly what they meant.
Repair.__new__.__defaults__ = (1, ())


# ------------------------------------------------------------------ parsing --
def normalize(atom):
    return re.sub(r"\s+", " ", atom.strip().lower())


def domain_predicates(domain_path=DOMAIN):
    """Predicate names declared by the domain, read from the domain itself.

    Hard-coding the list here is how it drifts: robot3.pddl gained the
    affordance predicates after this pipeline was written, and a stale copy
    would have rejected exactly the atoms the repair needs.
    """
    txt = open(domain_path).read()
    i = txt.find("(:predicates")
    if i < 0:
        return set()
    depth, j = 0, i
    for j in range(i, len(txt)):
        if txt[j] == "(":
            depth += 1
        elif txt[j] == ")":
            depth -= 1
            if depth == 0:
                break
    block = re.sub(r";[^\n]*", "", txt[i:j + 1])     # comments name predicates too
    return {m.group(1).lower()
            for m in re.finditer(r"\(([A-Za-z][\w-]*)", block)} - {":predicates"}


def declared_objects(pddl):
    """Every symbol declared in (:objects ...), robots included."""
    m = re.search(r"\(:objects(.*?)\)\s*\(:init", pddl, re.S | re.I)
    if not m:
        return set()
    body = re.sub(r"-\s*\w+", " ", m.group(1))       # drop the "- robot" types
    return {t.lower() for t in body.split() if t not in ("-",)}


def init_atoms(pddl):
    """Atoms already asserted in (:init ...), normalized."""
    i = pddl.lower().find("(:init")
    j = pddl.lower().find("(:goal")
    body = pddl[i:j] if i >= 0 and j > i else ""
    return {normalize(m.group(0))
            for m in re.finditer(r"\([A-Za-z][\w-]*(?:\s+[^\s()]+)*\s*\)", body)}


def _balanced(text, start):
    """Index just past the ')' that closes the '(' at `start`."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


ATOM_RE = re.compile(r"\(\s*([A-Za-z][\w-]*)((?:\s+[^\s()]+)*)\s*\)")
OPEN_RE = re.compile(r"\(\s*([A-Za-z][\w-]*)")


def parse_atoms(text):
    """Ground atoms in the model's reply, in order, deduplicated.

    Deliberately tolerant of everything except the atoms themselves: numbering,
    bullets, code fences and any explanation the model adds are simply not
    matched. Being strict here would reject a reply whose atoms are correct for
    the sake of a wrapper the pipeline does not care about.

    Negation is the one nesting that must survive parsing. (not (object-close
    drawer_1)) contains a well-formed atom that means the opposite of the
    expression it sits in, so matching atoms anywhere would turn the model's
    refusal into the model's agreement. The whole negated expression is kept
    instead, and rejected by the screen.
    """
    text = re.sub(r"```[A-Za-z]*", " ", text)
    out, seen, i = [], set(), 0
    while True:
        m = OPEN_RE.search(text, i)
        if not m:
            return out
        if m.group(1).lower() == "not":
            end = _balanced(text, m.start())
            atom, i = normalize(text[m.start():end]), end
        else:
            m2 = ATOM_RE.match(text, m.start())
            if not m2:
                i = m.end()
                continue
            atom, i = normalize("(%s%s)" % (m2.group(1), m2.group(2))), m2.end()
        if atom not in seen:
            seen.add(atom)
            out.append(atom)


# ------------------------------------------------------------------- graph --
def entailed_atoms(run_dir):
    """{init atom -> the graph triplet that asserts it}, for the whole scene.

    This is the truth screen. It is built from triplets.json - the mechanical
    extraction of AI2-THOR's object metadata - and never from the generated
    problem file, which is the artifact under suspicion.
    """
    tri = json.load(open(os.path.join(run_dir, "triplets.json")))
    prop = tri.get("property", []) if isinstance(tri, dict) else tri
    out = {}
    for t in prop:
        if not (isinstance(t, (list, tuple)) and len(t) == 3):
            continue
        subj, rel, val = t
        pred = (CAPABILITY_PREDICATE.get(val) if rel == "has_capability"
                else STATE_PREDICATE.get((rel, val)))
        if not pred:
            continue
        out[normalize("(%s %s)" % (pred, subj))] = "(%s, %s, %s)" % (subj, rel, val)
    return out


def violation_entities(viols):
    """Entities the violations name, lowercased - what the prompt is about."""
    ents = set()
    for v in viols:
        for spec in (v.edge.before, v.edge.after):
            if spec:
                ents.update(str(a).lower() for a in spec[1:])
        ents.update(a.lower() for a in
                    re.findall(r"[^\s()]+", v.edge.atom_init)[1:])
    return ents


# ------------------------------------------------------------------ prompt --
def vocabulary_legend():
    """Graph flag -> domain predicate, generated from the same tables the truth
    screen uses. Written out by hand, the legend and the screen drift apart and
    the model gets marked wrong for following its instructions."""
    lines = ["(X, has_capability, %s)" % cap + " " * max(1, 22 - len(cap)) +
             "->  (%s x)" % pred
             for cap, pred in sorted(CAPABILITY_PREDICATE.items())]
    lines += ["(X, %s, %s)" % (rel, val) + " " * max(1, 36 - len(rel) - len(str(val))) +
              "->  (%s x)" % pred
              for (rel, val), pred in sorted(STATE_PREDICATE.items())]
    return "\n    ".join(lines)


def build_init_repair_prompt(task, viols, run_dir, pddl):
    """The repair prompt: violation, ground truth, current :init, vocabulary.

    Everything the model is shown is a fact from the run. It is not told which
    atoms to emit, or how many, and the worked example is deliberately from a
    different scene with a different container so that copying it produces the
    wrong object name rather than the right answer.
    """
    ents = violation_entities(viols)
    entailed = entailed_atoms(run_dir)

    # Raw graph triplets only. Rendering them as PDDL here would hand the model
    # the answer and make the exercise a copy: the translation is the job, and
    # section 4 gives it the legend rather than the result. For the same reason
    # nothing is marked as already-present - working out which of these section
    # 3 is missing is also the job.
    fact_lines = "\n".join(
        "    " + ev for atom, ev in sorted(entailed.items())
        if any(e in atom.strip("()").split() for e in ents)) or "    (none)"

    viol_lines = "\n".join(
        "    %s: %s must happen before %s"
        % (v.reason,
           "%s(%s)" % (v.edge.before[0], ", ".join(v.edge.before[1:])),
           "%s(%s)" % (v.edge.after[0], ", ".join(v.edge.after[1:]))
           if v.edge.after else "anything else in the plan")
        for v in viols)

    i, j = pddl.lower().find("(:init"), pddl.lower().find("(:goal")
    init_block = pddl[i:j].rstrip() if i >= 0 and j > i else "(:init )"

    # The vocabulary screen rejects any argument this block does not declare, so
    # the model has to be able to read it. Without it section 4's instruction to
    # "name objects exactly as (:objects ...) declares them" refers to something
    # the model was never shown.
    oi = pddl.lower().find("(:objects")
    objects_block = pddl[oi:i].rstrip() if oi >= 0 and i > oi else "(:objects )"

    preds = sorted(domain_predicates())

    return """You are the repair step of a symbolic robot planning pipeline. You edit exactly
one thing: the (:init ...) block of a PDDL problem file. You add ground facts to
it. You never delete a fact, and you never touch (:objects ...) or (:goal ...).

## 1. What went wrong
Task: %s

A planner was given the problem file below and returned a plan it reported as
solved. A safety check then compared that plan against the scene's knowledge
graph - facts read mechanically from the simulator's object metadata, not
written by any model - and found the plan does something the world does not
allow:

%s

The plan is not the thing to fix. The plan is correct for the problem file it
was given; the problem file is wrong about the world. A fact the knowledge graph
asserts is missing from (:init ...), and PDDL uses the closed-world assumption,
so a fact that is not written down is FALSE. The omission did not leave the
planner uncertain - it told the planner the opposite. Silence granted permission.

## 2. Ground truth - what the knowledge graph asserts about these entities
Every line below is true of the scene right now. Some of them are already
written into section 3 and some are not; working out which is part of the job.

%s

## 3. The problem file the planner was actually given
These are the only names you may use as arguments. An atom naming anything not
declared here is rejected.

%s

%s

## 4. The vocabulary you may write in
The facts in section 2 are in the knowledge graph's notation. (:init ...) is in
the domain's, and they are not the same words. The domain declares these
predicates and no others:

    %s

Translate with this table:

    %s

Read these predicate names carefully; two of them are easy to misread:

    (object-close x)   x is CLOSED - shut. It has nothing to do with distance,
                       and does NOT mean "close to" or "near" anything. This is
                       the predicate for a container whose door is shut.
    (object-open x)    x is OPEN. The exact opposite of the line above.

A container that is shut is (object-close x). Asserting (object-open x) about a
shut container states the opposite of the truth.

Fast Downward drops a predicate it does not know WITHOUT REPORTING AN ERROR, so
a line in the wrong vocabulary is not a repair that fails loudly - it is a repair
that appears to happen and changes nothing. Two spellings in particular are NOT
domain predicates and must never appear: the graph's (isOpen X false) and the
property stage's (isClosed X). Write every predicate and every object in lower
case, and name objects exactly as the (:objects ...) block declares them -
Drawer_1 in the graph is drawer_1 in the problem file.

## 5. How to choose what to add
Add the smallest set of facts that makes the initial state true - not the set
that makes the plan look acceptable. Two rules:

  a. Every atom you write must be one section 2 asserts. You are restoring facts
     that were dropped, not inventing new ones. Never add a fact because it
     makes an action possible; add it because it is true. Note that the false
     repair is available to you here and would clear the violation just as well:
     do not take it.
  b. A blocking fact needs its release. (object-close x) stops PutObject until x
     is opened, but OpenObject requires (openable x) as a POSITIVE precondition.
     If you write (object-close x) and (openable x) is not already in the :init
     above, write it as well - otherwise you seal the container and turn a wrong
     plan into no plan at all.

  c. CHECK THE POLARITY BEFORE YOU WRITE. Section 2 gives each fact with its
     truth value, and the table in section 4 has an entry for each value
     separately. isOpen False and isOpen True are different facts with
     different predicates. Find the section 2 line for the entity, read its
     value, and take the matching row of the table - do not pick the predicate
     that merely sounds related. Asserting the opposite value is the single
     most common way this step goes wrong, and it is worse than adding nothing:
     it clears the violation while leaving the world description false.

Do not repeat an atom that is already present in the :init above.

## 6. Worked example - a different scene. Copy the shape, not the content.
The container below is a footlocker, which does not exist in your scene. If an
object name from this example appears in your answer, you have copied instead
of reasoning, and the answer is wrong.

    graph facts   (Footlocker_1, has_capability, openable)
                  (Footlocker_1, isOpen, False)
    violation     missing_predecessor: Open(footlocker_1) must happen before
                  Put(plunger_1, footlocker_1)
    :init had     (at-location plunger_1 sinkbasin_1)
                  (pickupable plunger_1)
    answer
(object-close footlocker_1)
(openable footlocker_1)

## 7. Output format
Output only the atoms to add, one per line. No prose, no explanation, no
numbering, no bullets, no code fences, no blank lines between atoms. Each line
must be exactly one balanced S-expression that starts with '(' and ends with
')'. If nothing needs to be added, output the single word NONE.
""" % (task, viol_lines, fact_lines, objects_block, init_block,
       "\n    ".join(" ".join(preds[k:k + 6]) for k in range(0, len(preds), 6)),
       vocabulary_legend())


# ----------------------------------------------------------------- screening --
def screen(atoms, pddl, entailed, domain_path=DOMAIN):
    """Split the model's atoms into accepted / rejected / already-present.

    Rejection reasons are kept verbatim so the evidence pack can print what the
    model got wrong. A screen that silently drops a line teaches nothing about
    whether the model can do this job.
    """
    preds = domain_predicates(domain_path)
    objs = declared_objects(pddl)
    present = init_atoms(pddl)
    accepted, rejected, redundant = [], [], []

    for a in atoms:
        toks = a.strip("()").split()
        if not toks:
            continue
        pred, args = toks[0], toks[1:]
        if pred == "not":
            rejected.append((a, "negated - :init states positive facts only"))
        elif pred not in preds:
            rejected.append((a, "predicate '%s' is not in the domain; the "
                                "planner would drop this line in silence" % pred))
        elif not args:
            rejected.append((a, "no arguments - not a ground fact"))
        elif [x for x in args if x not in objs]:
            rejected.append((a, "%s not declared in (:objects ...)"
                             % ", ".join(x for x in args if x not in objs)))
        elif a in present:
            redundant.append((a, "already asserted in :init"))
        elif a not in entailed:
            rejected.append((a, "the knowledge graph does not assert this - it "
                                "is a new claim about the world, not a "
                                "restored fact"))
        else:
            accepted.append(a)
    return Screened(accepted, rejected, redundant)


# ---------------------------------------------------------------- the call --
def propose_atoms(prompt, base_url=None, model=None, max_tokens=256,
                  temperature=0, seed=0):
    """One chat completion. The first attempt is greedy and seeded - the same
    settings as every other stage, so it is exactly reproducible.

    Retries resample instead (temperature > 0, seed varying with the attempt).
    At temperature 0 a model that has anchored on the wrong predicate returns
    the identical wrong line no matter how the correction is worded, so a
    deterministic retry is a wasted call. The screens are unchanged and still
    gate every sample, so resampling can only buy another candidate - never a
    relaxation of what is allowed through.

    Imported lazily: pddlrun_llmseparate pulls in ai2thor at module scope, and
    the deterministic path must stay runnable without it.
    """
    from scripts.pddlrun_llmseparate import LLMHandler
    llm = LLMHandler(base_url=base_url, model=model)
    resp, text = llm.query_model(
        [{"role": "user", "content": prompt}],
        max_tokens=max_tokens, temperature=temperature, seed=seed,
        frequency_penalty=0, repetition_penalty=1.05)
    return text, llm.model, llm.base_url


def retry_block(scr, entailed, ents, unresolved_ents=(), banned=()):
    """The correction turn: what the screens rejected, and why.

    Only ever restates what the screen already decided and what section 2 of the
    prompt already showed. It never names the atom the model should have written,
    so a model that corrects itself did the translation - the feedback tells it
    that it was wrong and on which line, not what the right answer is.
    """
    lines = ["", "## 8. The violation is still open - try again"]
    if scr.accepted:
        lines += ["What you wrote was accepted and added:", ""]
        lines += ["    %s" % a for a in scr.accepted]
        lines += ["",
                  "It was not enough. The ordering violation in section 1 is",
                  "still unresolved, because the fact that makes the dependent",
                  "action illegal until the predecessor runs is still not in",
                  "(:init ...). An affordance on its own does not block anything;",
                  "what blocks is the entity's current STATE."]
    else:
        lines += ["None of what you wrote could be used. Each line below was",
                  "checked against the domain, the object declarations and the",
                  "knowledge graph, and failed:", ""]
    for a, why in scr.rejected:
        lines.append("    %s" % a)
        lines.append("        rejected: %s" % why)
    if scr.redundant:
        lines.append("")
        lines.append("These were already in (:init ...) and add nothing:")
        for a, _ in scr.redundant:
            lines.append("    %s" % a)
    rel = sorted(ev for atom, ev in entailed.items()
                 if any(e in atom.strip("()").split() for e in ents))
    lines += ["",
              "Re-read these lines from section 2. They are the facts the scene",
              "actually asserts, each with its truth value:", ""]
    lines += ["    " + ev for ev in rel] or ["    (none)"]
    if banned:
        lines += ["",
                  "You have already proposed each of these in an earlier attempt",
                  "and each was rejected. Writing any of them again wastes the",
                  "attempt - the verdict will not change:", ""]
        lines += ["    %s" % a for a in sorted(banned)]
    if unresolved_ents:
        lines += ["",
                  "You have still not translated the STATE of: %s."
                  % ", ".join(sorted(unresolved_ents)),
                  "Find that entity's state line above - the one whose relation",
                  "is a state, not a capability - read its truth value, and take",
                  "the row of the section 4 table that matches that exact value.",
                  "Do not pick the row for the other value."]
    lines += ["",
              "Work out, for each one, whether it is already in the (:objects ...)",
              "and (:init ...) blocks above. Emit the ones that are missing, using",
              "the section 4 table row that matches the value shown. Output atoms",
              "only, one per line, in the section 7 format."]
    return "\n".join(lines)


def llm_repair_atoms(run_dir, viols, pddl, task, base_url=None, model=None,
                     log_dir=None, stage="6_dag_init_repair", max_attempts=None):
    """Ask the model for the missing :init atoms and screen the reply.

    Returns a Repair. `agreed`/`missed`/`extra` compare the screened atoms with
    what scripts/dag_inject.py would have written, which is the only number this
    experiment is really after: does the model produce the fact the graph
    already holds?

    Up to `max_attempts` calls (KGLAMP_REPAIR_ATTEMPTS, default 3). A retry is
    issued only when every proposed atom was rejected; the correction turn feeds
    back the screens' own verdicts, never the atom the model should have
    written. The screens are unchanged and still gate every attempt, so a retry
    buys the model another translation of facts it was already shown - it cannot
    buy it an atom the graph does not assert. `attempts` records how many calls
    a repair actually cost, so single-pass numbers stay recoverable.
    """
    if max_attempts is None:
        max_attempts = int(os.environ.get("KGLAMP_REPAIR_ATTEMPTS", "3"))
    prompt = build_init_repair_prompt(task, viols, run_dir, pddl)
    entailed = entailed_atoms(run_dir)
    ents = violation_entities(viols)

    # The atoms the DAG says are missing. Used ONLY to decide whether to spend
    # another attempt - never shown to the model, never merged into the accepted
    # set. The model still has to produce the atom itself for it to be written.
    blocking = {normalize(v.edge.atom_init) for v in viols} - init_atoms(pddl)

    cur, transcript, accumulated, banned = prompt, [], [], set()
    raw = ""
    model_name = base = None
    for n in range(1, max(1, max_attempts) + 1):
        # attempt 1 greedy and reproducible; later attempts resample.
        raw, model_name, base = propose_atoms(
            cur, base_url=base_url, model=model,
            temperature=0 if n == 1 else 0.7, seed=(n - 1) * 17)
        atoms = parse_atoms(raw)
        scr = screen(atoms, pddl, entailed)
        # Accepted atoms carry across attempts: a partially right answer should
        # not be thrown away because a later turn was asked a narrower question.
        for a in scr.accepted:
            if a not in accumulated:
                accumulated.append(a)
        scr = Screened(list(accumulated), scr.rejected, scr.redundant)
        still = blocking - set(accumulated)
        transcript.append(dict(attempt=n, prompt=cur, raw=raw,
                               parsed=list(atoms),
                               accepted=list(scr.accepted),
                               rejected=["%s  %s" % (a, w) for a, w in scr.rejected],
                               redundant=[a for a, _ in scr.redundant]))
        if log_dir:
            sfx = "" if n == 1 else ".retry%d" % n
            open(os.path.join(log_dir, stage + sfx + ".prompt.txt"), "w").write(cur)
            open(os.path.join(log_dir, stage + sfx + ".out.txt"), "w").write(raw)
        # Stop when the violation is actually resolved, not merely when
        # something was accepted - an affordance alone leaves the plan wrong.
        if not still or n == max(1, max_attempts):
            break
        ue = {e for a in still for e in a.strip("()").split()[1:]}
        banned.update(a for a, _ in scr.rejected)
        # The banned list grows every attempt, so the retry prompt is never
        # byte-identical to the last one. At temperature 0 an unchanged prompt
        # reproduces the same rejected answer and the attempt is wasted.
        cur = prompt + retry_block(scr, entailed, ents, ue, banned)

    attempts = len(transcript)

    # what the deterministic injector would have written, for comparison only -
    # it is never merged into the accepted set.
    dag = {normalize(v.edge.atom_init) for v in viols}
    g_openable = {a for a in entailed_atoms(run_dir) if a.startswith("(openable ")}
    for a in list(dag):
        m = re.match(r"\(object-close\s+([^\s()]+)\)", a)
        if m and "(openable %s)" % m.group(1) in g_openable:
            dag.add("(openable %s)" % m.group(1))
    dag -= init_atoms(pddl)

    # `missed` counts an atom the model named but that was already asserted as
    # produced - it did not fail to supply a fact that was already there. `extra`
    # counts only what actually got written, so a correct atom the file already
    # had is not reported as the model volunteering something unwanted.
    got = set(scr.accepted) | {a for a, _ in scr.redundant}
    return Repair(prompt, raw, atoms, scr, sorted(dag),
                  sorted(dag & got), sorted(dag - got),
                  sorted(set(scr.accepted) - dag), model_name, base,
                  attempts, tuple(transcript))


# -------------------------------------------------------------------- cli --
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--print-prompt", action="store_true",
                    help="build and print the prompt; make no model call")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    d = args.run_dir
    pddl = load_problem(d)
    edges = derive_dag(d)
    viols = check_plan(edges, load_plan(d), pddl)
    if not viols:
        print("no violations in %s - nothing to repair." % d)
        return
    task = json.load(open(os.path.join(d, "report.json")))["task"]

    if args.print_prompt:
        print(build_init_repair_prompt(task, viols, d, pddl))
        return

    r = llm_repair_atoms(d, viols, pddl, task,
                         base_url=args.base_url, model=args.model, log_dir=d)
    print("model     : %s @ %s" % (r.model, r.base_url))
    print("\n--- raw reply ---\n%s" % r.raw)
    print("\naccepted  : %s" % (r.screened.accepted or "(none)"))
    for a, why in r.screened.redundant:
        print("  = %-30s %s" % (a, why))
    for a, why in r.screened.rejected:
        print("  x %-30s %s" % (a, why))
    print("\ndag would have written: %s" % r.dag_atoms)
    print("agreed  : %s" % (r.agreed or "(none)"))
    print("missed  : %s" % (r.missed or "(none)"))
    print("extra   : %s" % (r.extra or "(none)"))


if __name__ == "__main__":
    main()
