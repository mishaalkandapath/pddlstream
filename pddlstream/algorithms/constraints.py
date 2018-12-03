from collections import namedtuple
from copy import deepcopy

from pddlstream.algorithms.downward import make_predicate, make_preconditions, make_effects
from pddlstream.language.constants import Or, And, is_parameter, Equal, Not
from pddlstream.language.conversion import obj_from_value_expression
from pddlstream.language.object import Object
from pddlstream.utils import find_unique, safe_zip

# TODO: multiple plans, partially ordered, AND/OR tree

ANY = '*'
ASSIGNED_PREDICATE = 'assigned'
ORDER_PREDICATE = 'order'

PlanConstraints = namedtuple('PlanConstraints', ['skeletons', 'exact', 'hint'])

def to_constant(parameter):
    name = parameter[1:]
    return '@{}'.format(name)


def add_plan_constraints(constraints, domain, init, new_goal):
    import pddl
    [skeleton] = constraints.skeletons
    # TODO: can search over skeletons first and then fall back
    # TODO: unify this with the constraint ordering

    order_value_facts = [(ORDER_PREDICATE, 't{}'.format(i)) for i in range(len(skeleton) + 1)]
    init.append(order_value_facts[0])
    new_goal = And(new_goal, Or(order_value_facts[-1]))
    domain.predicate_dict[ORDER_PREDICATE] = make_predicate(ORDER_PREDICATE, ['?x'])

    order_facts = list(map(obj_from_value_expression, order_value_facts))
    bound_parameters = set()
    new_actions = []
    for i, (name, args) in enumerate(skeleton):
        # TODO: could also just remove the free parameter from the action
        action = find_unique(lambda a: a.name == name, domain.actions)
        new_action = deepcopy(action)
        assert len(args) == len(new_action.parameters)
        arg_from_parameter = {p.name: a for p, a in safe_zip(new_action.parameters, args)}
        #free = [p.name for a, p in safe_zip(args, new_action.parameters) if is_parameter(a)]
        #wildcards = [p.name for a, p in safe_zip(args, new_action.parameters) if a == ANY]
        constants = [p.name for a, p in safe_zip(args, new_action.parameters)
                     if not is_parameter(a) and a != ANY]
        skeleton_parameters = list(filter(is_parameter, args))
        existing_parameters = [p for p in skeleton_parameters if p in bound_parameters]
        local_from_global = {a: p.name for a, p in safe_zip(args, new_action.parameters) if is_parameter(a)}

        new_preconditions = [(ASSIGNED_PREDICATE, to_constant(p), local_from_global[p])
                             for p in existing_parameters] + [order_facts[i]] + \
                            [Equal(p, Object.from_value(arg_from_parameter[p])) for p in constants]
        new_action.precondition = pddl.Conjunction(
            [new_action.precondition, make_preconditions(new_preconditions)]).simplified()

        new_effects = [(ASSIGNED_PREDICATE, to_constant(p), local_from_global[p])
                       for p in skeleton_parameters] + [Not(order_facts[i]), order_facts[i + 1]]
        new_action.effects.extend(make_effects(new_effects))

        new_actions.append(new_action)
        bound_parameters.update(skeleton_parameters)
    if constraints.exact:
        domain.actions[:] = []
    domain.actions.extend(new_actions)
    return new_goal