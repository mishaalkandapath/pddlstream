from collections import namedtuple, defaultdict
from heapq import heappop, heappush

from pddlstream.language.conversion import is_atom, fact_from_evaluation
from pddlstream.utils import HeapElement

Node = namedtuple('Node', ['effort', 'stream_result']) # TODO: level

NULL_COND = (None,)

def get_achieving_streams(evaluations, stream_results, op=sum, unit_effort=False):
    # TODO: could do this with bound_stream_instances instead
    unprocessed_from_atom = defaultdict(list)
    node_from_atom = {NULL_COND: Node(0, None)}
    conditions_from_stream = {}
    remaining_from_stream = {}
    for result in stream_results:
        conditions_from_stream[result] = result.instance.get_domain() + (NULL_COND,)
        remaining_from_stream[result] = len(conditions_from_stream[result])
        for atom in conditions_from_stream[result]:
            unprocessed_from_atom[atom].append(result)
    for atom in evaluations:
        if is_atom(atom):
            node_from_atom[fact_from_evaluation(atom)] = Node(0, None)

    queue = [HeapElement(node.effort, atom) for atom, node in node_from_atom.items()]
    while queue:
        atom = heappop(queue).value
        if atom not in unprocessed_from_atom:
            continue
        for result in unprocessed_from_atom[atom]:
            remaining_from_stream[result] -= 1
            if remaining_from_stream[result]:
                continue
            effort = 1 if unit_effort else result.instance.get_effort()
            total_effort = effort + op(node_from_atom[cond].effort for cond in conditions_from_stream[result])
            for new_atom in result.get_certified():
                if (new_atom not in node_from_atom) or (total_effort < node_from_atom[new_atom].effort):
                    node_from_atom[new_atom] = Node(total_effort, result)
                    heappush(queue, HeapElement(total_effort, new_atom))
        del unprocessed_from_atom[atom]
    del node_from_atom[NULL_COND]
    return node_from_atom


def extract_stream_plan(node_from_atom, target_facts, stream_plan):
    # TODO: prune with rules
    # TODO: linearization that takes into account satisfied goals at each level
    # TODO: can optimize for all streams & axioms all at once
    for fact in target_facts:
        if fact not in node_from_atom:
            raise RuntimeError('Preimage fact {} is not achievable!'.format(fact))
        stream_result = node_from_atom[fact].stream_result
        if (stream_result is None) or (stream_result in stream_plan):
            continue
        extract_stream_plan(node_from_atom, stream_result.instance.get_domain(), stream_plan)
        stream_plan.append(stream_result) # TODO: don't add if satisfied