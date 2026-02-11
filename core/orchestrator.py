# File: core/orchestrator.py | Module: orchestrator | Part of Intellectual Property Submission.
"""Recursive orchestration logic for the multi-agent marketing pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence

from storage.db import Database
from storage.vector_store import InMemoryVectorStore

from .agents import (
    AgentContext,
    Agent_Analyst,
    Agent_Copywriter,
    Agent_Interviewer,
    Agent_Visual_Director,
    BaseAgent,
)
from .notification_bridge import ApprovalDecision, NotificationBridge


class AgentState(Enum):
    """Finite state machine values used by the orchestrator."""

    IDLE = "IDLE"
    DATA_COLLECTED = "DATA_COLLECTED"
    MARKET_ANALYZED = "MARKET_ANALYZED"
    CONTENT_READY = "CONTENT_READY"
    AWAITING_USER_DECISION = "AWAITING_USER_DECISION"
    USER_APPROVED = "USER_APPROVED"
    ERROR = "ERROR"


class UserApprovalNode:
    """Human-in-the-loop node that captures approval decisions."""

    # Step 1: Initialize approval node dependencies.
    def __init__(self, bridge: NotificationBridge) -> None:
        self.bridge = bridge

    # Step 2: Request user decision through the notification bridge.
    def intercept(self, context: AgentContext) -> ApprovalDecision:
        if context.post_draft is None:
            raise ValueError("Post draft is required before requesting user approval.")

        decision = self.bridge.notify_content_ready(context.post_draft.text)
        context.approval_status = decision.value
        context.pending_user_action = decision != ApprovalDecision.APPROVED
        context.add_log(f"UserApprovalNode: decision={decision.value}.")
        return decision

    # Step 3: Apply an externally provided command to the current context.
    def apply_user_command(self, context: AgentContext, command: str) -> ApprovalDecision:
        normalized_command = command.strip().upper()
        decision = ApprovalDecision(normalized_command)
        context.approval_status = decision.value
        context.pending_user_action = decision != ApprovalDecision.APPROVED
        context.add_log(f"UserApprovalNode: external command applied ({decision.value}).")
        return decision


class AgentOrchestrator:
    """Orchestrator implementing recursive state transitions and regeneration logic."""

    # Step 4: Initialize orchestrator internals and bind agent references.
    def __init__(
        self,
        agents: Sequence[BaseAgent],
        approval_node: Optional[UserApprovalNode] = None,
        require_user_approval: bool = False,
        max_cycles: int = 30,
    ) -> None:
        self.agents = list(agents)
        self.current_state = AgentState.IDLE
        self.approval_node = approval_node
        self.require_user_approval = require_user_approval
        self.max_cycles = max_cycles

        self._agent_by_name = {agent.name: agent for agent in self.agents}
        self._interviewer = self._agent_by_name.get("Agent_Interviewer")
        self._analyst = self._agent_by_name.get("Agent_Analyst")
        self._copywriter = self._agent_by_name.get("Agent_Copywriter")
        self._visual = self._agent_by_name.get("Agent_Visual_Director")

    # Step 5: Transition the state machine to the provided state.
    def transition_to(self, new_state: AgentState) -> None:
        self.current_state = new_state

    # Step 6: Execute one agent safely and propagate failure state on exception.
    def _execute_agent(self, context: AgentContext, agent: Optional[BaseAgent]) -> AgentContext:
        if agent is None:
            raise RuntimeError("Required agent is not configured in orchestrator.")

        agent.check_state(self.current_state.value)
        context.add_log(f"AgentOrchestrator: executing {agent.name}.")
        try:
            return agent.run(context)
        except Exception:
            self.transition_to(AgentState.ERROR)
            raise

    # Step 7: Resolve a user decision and update pipeline state transitions.
    def _handle_decision(self, context: AgentContext, decision: ApprovalDecision) -> Optional[AgentContext]:
        if decision == ApprovalDecision.APPROVED:
            self.transition_to(AgentState.USER_APPROVED)
            return context

        if decision == ApprovalDecision.REGENERATE:
            context.pending_user_action = False
            context.approval_status = None
            context.user_event_type = None
            context.user_event_context = None
            self.transition_to(AgentState.MARKET_ANALYZED)
            context.add_log("AgentOrchestrator: regeneration requested; resetting to MARKET_ANALYZED.")
            return None

        if decision == ApprovalDecision.EDIT:
            if context.user_event_type:
                if self._copywriter is None:
                    raise RuntimeError("Copywriter agent is required for edit events.")
                context = self._copywriter.process_user_event(
                    context=context,
                    event_type=context.user_event_type,
                    event_context=context.user_event_context or "",
                )
                context.user_event_type = None
                context.user_event_context = None
                self.transition_to(AgentState.CONTENT_READY)
                context.add_log("AgentOrchestrator: edit event applied; returning to CONTENT_READY.")
                return None

            self.transition_to(AgentState.AWAITING_USER_DECISION)
            context.pending_user_action = True
            context.add_log("AgentOrchestrator: edit requested; awaiting detailed user event context.")
            return context

        self.transition_to(AgentState.AWAITING_USER_DECISION)
        context.pending_user_action = True
        context.add_log("AgentOrchestrator: awaiting user decision.")
        return context

    # Step 8: Execute recursive orchestration until USER_APPROVED or user interaction pause.
    def run_pipeline(self, context: AgentContext) -> AgentContext:
        cycles = 0

        while self.current_state != AgentState.USER_APPROVED:
            cycles += 1
            if cycles > self.max_cycles:
                raise RuntimeError("Maximum orchestration cycles exceeded.")

            if self.current_state == AgentState.IDLE:
                context.validate("IDLE")
                context = self._execute_agent(context, self._interviewer)
                self.transition_to(AgentState.DATA_COLLECTED)
                continue

            if self.current_state == AgentState.DATA_COLLECTED:
                context.validate("DATA_COLLECTED")
                context = self._execute_agent(context, self._analyst)
                self.transition_to(AgentState.MARKET_ANALYZED)
                continue

            if self.current_state == AgentState.MARKET_ANALYZED:
                context = self._execute_agent(context, self._copywriter)
                self.transition_to(AgentState.CONTENT_READY)
                continue

            if self.current_state == AgentState.CONTENT_READY:
                context = self._execute_agent(context, self._visual)

                if not self.require_user_approval:
                    self.transition_to(AgentState.USER_APPROVED)
                    continue

                if self.approval_node is None:
                    raise RuntimeError("UserApprovalNode is required when human approval is enabled.")

                decision = self.approval_node.intercept(context)
                handled = self._handle_decision(context, decision)
                if handled is not None:
                    return handled
                continue

            if self.current_state == AgentState.AWAITING_USER_DECISION:
                if self.approval_node is None:
                    raise RuntimeError("UserApprovalNode is required in AWAITING_USER_DECISION state.")

                status_value = (context.approval_status or "").strip().upper()
                if not status_value or status_value == ApprovalDecision.AWAITING_USER_ACTION.value:
                    context.pending_user_action = True
                    context.add_log("AgentOrchestrator: paused in AWAITING_USER_DECISION state.")
                    return context

                decision = self.approval_node.apply_user_command(context, status_value)
                handled = self._handle_decision(context, decision)
                if handled is not None:
                    return handled
                continue

            if self.current_state == AgentState.ERROR:
                raise RuntimeError("Orchestration terminated due to a previous error state.")

            raise RuntimeError(f"Unsupported orchestrator state: {self.current_state.value}")

        context.pending_user_action = False
        context.approval_status = ApprovalDecision.APPROVED.value
        context.add_log("AgentOrchestrator: pipeline completed with USER_APPROVED state.")
        return context

    # Step 9: Maintain compatibility with existing callers by delegating to run_pipeline.
    def run(self, context: AgentContext) -> AgentContext:
        return self.run_pipeline(context)


# Step 10: Build default orchestrator chain with user-approval interception enabled.
def build_default_orchestrator(database: Optional[Database] = None) -> AgentOrchestrator:
    vector_store = InMemoryVectorStore()
    agents = [
        Agent_Interviewer(database=database),
        Agent_Analyst(),
        Agent_Copywriter(vector_store=vector_store),
        Agent_Visual_Director(),
    ]
    approval_node = UserApprovalNode(bridge=NotificationBridge())
    return AgentOrchestrator(agents=agents, approval_node=approval_node, require_user_approval=True)


__all__ = [
    "AgentContext",
    "AgentOrchestrator",
    "AgentState",
    "UserApprovalNode",
    "build_default_orchestrator",
]
