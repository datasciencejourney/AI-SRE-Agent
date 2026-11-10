from langgraph.graph import END, START, StateGraph

from app.orchestrator import nodes
from app.orchestrator.state import IncidentState

INVESTIGATORS = ["logs_agent", "metrics_agent", "deploy_agent", "db_agent"]


def build_graph(checkpointer):
    g = StateGraph(IncidentState)

    g.add_node("triage", nodes.triage)
    g.add_node("start_round", nodes.start_round)
    g.add_node("logs_agent", nodes.logs_agent)
    g.add_node("metrics_agent", nodes.metrics_agent)
    g.add_node("deploy_agent", nodes.deploy_agent)
    g.add_node("db_agent", nodes.db_agent)
    g.add_node("hypothesis", nodes.hypothesis)
    g.add_node("critic", nodes.critic)
    g.add_node("propose_fix", nodes.propose_fix)
    g.add_node("approval_gate", nodes.approval_gate)
    g.add_node("execute", nodes.execute)
    g.add_node("verify", nodes.verify)
    g.add_node("escalate", nodes.escalate)
    g.add_node("postmortem", nodes.postmortem)

    g.add_edge(START, "triage")
    g.add_edge("triage", "start_round")
    for name in INVESTIGATORS:  # fan out: the four investigators run in parallel
        g.add_edge("start_round", name)
    g.add_edge(INVESTIGATORS, "hypothesis")  # fan in: wait for all four
    g.add_edge("hypothesis", "critic")

    g.add_conditional_edges("critic", nodes.after_critic, ["propose_fix", "start_round", "escalate"])
    g.add_conditional_edges("propose_fix", nodes.after_propose, ["approval_gate", "postmortem"])
    g.add_conditional_edges("approval_gate", nodes.after_approval, ["execute", "escalate"])
    g.add_edge("execute", "verify")
    g.add_conditional_edges("verify", nodes.after_verify, ["postmortem", "escalate"])
    g.add_edge("escalate", "postmortem")
    g.add_edge("postmortem", END)

    return g.compile(checkpointer=checkpointer)
