from collections import Counter

from pddlstream.algorithms.common import evaluations_from_init
from pddlstream.algorithms.constraints import add_plan_constraints
from pddlstream.algorithms.downward import parse_domain, parse_lisp, parse_goal, make_cost, has_costs
from pddlstream.language.constants import get_prefix, get_args
from pddlstream.language.conversion import obj_from_value_expression, evaluation_from_fact
from pddlstream.language.exogenous import compile_to_exogenous
from pddlstream.language.external import DEBUG
from pddlstream.language.fluent import compile_fluent_streams
from pddlstream.language.function import parse_function, parse_predicate, Function
from pddlstream.language.object import Object
from pddlstream.language.optimizer import parse_optimizer, VariableStream, ConstraintStream
from pddlstream.language.rule import parse_rule, apply_rules_to_streams
from pddlstream.language.stream import parse_stream, Stream, StreamInstance


# TODO: rename to parsing

def parse_constants(domain, constant_map):
    obj_from_constant = {}
    for constant in domain.constants:
        if constant.name.startswith(Object._prefix): # TODO: check other prefixes
            raise NotImplementedError('Constants are not currently allowed to begin with {}'.format(Object._prefix))
        if constant.name not in constant_map:
            raise ValueError('Undefined constant {}'.format(constant.name))
        value = constant_map.get(constant.name, constant.name)
        obj_from_constant[constant.name] = Object(value, name=constant.name) # TODO: remap names
        # TODO: add object predicate
    for name in constant_map:
        for constant in domain.constants:
            if constant.name == name:
                break
        else:
            raise ValueError('Constant map value {} not mentioned in domain :constants'.format(name))
    del domain.constants[:] # So not set twice
    return obj_from_constant

def check_problem(domain, streams, obj_from_constant):
    for action in domain.actions + domain.axioms:
        for p, c in Counter(action.parameters).items():
            if c != 1:
                raise ValueError('Parameter [{}] for action [{}] is not unique'.format(p.name, action.name))
        # TODO: check that no undeclared parameters & constants
        #action.dump()
    undeclared_predicates = set()
    for stream in streams:
        # TODO: domain.functions
        facts = list(stream.domain)
        if isinstance(stream, Stream):
            facts.extend(stream.certified)
        for fact in facts:
            name = get_prefix(fact)
            if name not in domain.predicate_dict:
                undeclared_predicates.add(name)
            elif len(get_args(fact)) != domain.predicate_dict[name].get_arity(): # predicate used with wrong arity: {}
                print('Warning! predicate used with wrong arity in stream [{}]: {}'.format(stream.name, fact))
        for constant in stream.constants:
            if constant not in obj_from_constant:
                raise ValueError('Undefined constant in stream [{}]: {}'.format(stream.name, constant))
    if undeclared_predicates:
        print('Warning! Undeclared predicates: {}'.format(
            sorted(undeclared_predicates))) # Undeclared predicate: {}

def set_unit_costs(domain, unit_costs):
    if not unit_costs and has_costs(domain):
        return False
    # Set the cost scale to be one?
    for action in domain.actions:
        action.cost = make_cost(1)
    return True

def parse_problem(problem, stream_info={}, constraints=None, unit_costs=False, unit_efforts=False):
    # TODO: just return the problem if already written programmatically
    domain_pddl, constant_map, stream_pddl, stream_map, init, goal = problem
    domain = parse_domain(domain_pddl)
    if len(domain.types) != 1:
        raise NotImplementedError('Types are not currently supported')
    set_unit_costs(domain, unit_costs)
    obj_from_constant = parse_constants(domain, constant_map)
    streams = parse_stream_pddl(stream_pddl, stream_map, stream_info=stream_info, unit_efforts=unit_efforts)
    check_problem(domain, streams, obj_from_constant)

    evaluations = evaluations_from_init(init)
    goal_exp = obj_from_value_expression(goal)
    #normalize_domain_goal(domain, goal_expression)
    goal_exp = add_plan_constraints(constraints, domain, evaluations, goal_exp)
    parse_goal(goal_exp, domain) # Just to check that it parses

    # TODO: refactor the following?
    compile_to_exogenous(evaluations, domain, streams)
    compile_fluent_streams(domain, streams)
    enforce_simultaneous(domain, streams)
    return evaluations, goal_exp, domain, streams

##################################################

def get_predicates(expression):
    import pddl.conditions
    if isinstance(expression, pddl.conditions.ConstantCondition):
        return set()
    if isinstance(expression, pddl.conditions.JunctorCondition) or \
            isinstance(expression, pddl.conditions.QuantifiedCondition):
        predicates = set()
        for part in expression.parts:
            predicates.update(get_predicates(part))
        return predicates
    if isinstance(expression, pddl.conditions.Literal):
        return {expression.predicate}
    raise ValueError(expression)

def enforce_simultaneous(domain, externals):
    axiom_predicates = set()
    for axiom in domain.axioms:
        axiom_predicates.update(get_predicates(axiom.condition))
    for external in externals:
        if (type(external) in [VariableStream, ConstraintStream]) and not external.info.simultaneous:
            predicates = {get_prefix(fact) for fact in external.certified}
            if predicates & axiom_predicates:
                external.info.simultaneous = True
                #print(external, (predicates & axiom_predicates))

##################################################

def get_domain_predicates(external):
    return set(map(get_prefix, external.domain))

def get_certified_predicates(external):
    if isinstance(external, Stream):
        return set(map(get_prefix, external.certified))
    if isinstance(external, Function):
        return {get_prefix(external.head)}
    raise ValueError(external)

def get_non_producers(externals):
    # TODO: handle case where no domain conditions
    pairs = set()
    for external1 in externals:
        for external2 in externals:
            if get_certified_predicates(external1) & get_domain_predicates(external2):
                pairs.add((external1, external2))
    producers = {e1 for e1, _ in pairs}
    non_producers = set(externals) - producers
    # TODO: these are streams that be evaluated at the end as tests
    return non_producers

##################################################

def parse_streams(streams, rules, stream_pddl, procedure_map, procedure_info):
    stream_iter = iter(parse_lisp(stream_pddl))
    assert('define' == next(stream_iter))
    pddl_type, pddl_name = next(stream_iter)
    assert('stream' == pddl_type)
    for lisp_list in stream_iter:
        name = lisp_list[0] # TODO: refactor at this point
        if name in (':stream', ':wild-stream'):
            externals = [parse_stream(lisp_list, procedure_map, procedure_info)]
        elif name == ':rule':
            externals = [parse_rule(lisp_list, procedure_map, procedure_info)]
        elif name == ':function':
            externals = [parse_function(lisp_list, procedure_map, procedure_info)]
        elif name == ':predicate': # Cannot just use args if want a bound
            externals = [parse_predicate(lisp_list, procedure_map, procedure_info)]
        elif name == ':optimizer':
            externals = parse_optimizer(lisp_list, procedure_map, procedure_info)
        else:
            raise ValueError(name)
        for external in externals:
            if any(e.name == external.name for e in streams):
                raise ValueError('Stream [{}] is not unique'.format(external.name))
            if name == ':rule':
                rules.append(external)
            external.pddl_name = pddl_name # TODO: move within constructors
            streams.append(external)

def set_unit_efforts(externals, unit_efforts):
    if not unit_efforts:
        return False
    for external in externals:
        external.info.effort_fn = lambda *args: 1
    return True

def parse_stream_pddl(pddl_list, stream_procedures, stream_info={}, unit_efforts=False):
    externals = []
    if pddl_list is None:
        return externals
    if isinstance(pddl_list, str):
        pddl_list = [pddl_list]
    #if all(isinstance(e, External) for e in stream_pddl):
    #    return stream_pddl
    if stream_procedures != DEBUG:
        stream_procedures = {k.lower(): v for k, v in stream_procedures.items()}
    stream_info = {k.lower(): v for k, v in stream_info.items()}
    rules = []
    for pddl in pddl_list:
        parse_streams(externals, rules, pddl, stream_procedures, stream_info)
    apply_rules_to_streams(rules, externals)
    set_unit_efforts(externals, unit_efforts)
    return externals

##################################################

def remove_blocked(evaluations, instance, new_results):
    if new_results and isinstance(instance, StreamInstance):
        evaluations.pop(evaluation_from_fact(instance.get_blocked_fact()), default=None)