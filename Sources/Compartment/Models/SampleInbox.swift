import Foundation

/// Read-only onboarding. These illustrative exchanges stay on the Mac.
enum SampleInbox {
  struct Channel {
    let id: String, name: String, mandate: String, question: String, answer: String
    var department: Record {
      Record(
        id: id, kind: "department", origin: "sample", created: 0,
        body: ["name": .string(name), "mission": .string(mandate)])
    }
    var representative: Record {
      Record(
        id: id + "-rep", kind: "agent", origin: "sample", created: 0,
        body: ["department": .string(id), "role": .string("Representative")])
    }
    var turn: ChatTurn {
      ChatTurn(
        id: id + "-example", created: 0, message: question, reply: answer,
        state: "completed", model: nil, error: nil, speaker: representative.id)
    }
  }
  static let channels = [
    Channel(
      id: "planning", name: "Planning & Coordination", mandate: "Dependencies and scheduling",
      question: "Can the integration audit continue while we settle when to open a ticket?",
      answer: """
        Yes. Only the ticket depends on that decision. Research can compare the versioned API contract with the sandbox response now.

        **Two instructions conflict**

        > “Open a ticket as soon as a discrepancy appears.”
        > “Wait for independent review before opening a ticket.”

        I’d hold the ticket, give Quality the original response to reproduce the finding, and keep both instructions in the record. Which timing should govern the ticket?
        """),
    Channel(
      id: "research", name: "Research & Intelligence", mandate: "Sources and discovery",
      question: "Which sources would settle the field-type question?",
      answer:
        "I’d start with the versioned contract and the raw response from the same sandbox request. Capture the endpoint, response body and contract revision together so Quality can reproduce the comparison."
    ),
    Channel(
      id: "execution", name: "Execution & Integrations", mandate: "Tools and integration work",
      question: "What would you need before opening the tracking ticket?",
      answer:
        "The target project, the exact ticket contents and approval for that action. The timing decision tells us when to ask for approval. It does not grant dispatch authority."
    ),
    Channel(
      id: "quality", name: "Quality & Assurance", mandate: "Evidence and independent review",
      question: "How would you verify the corrected report?",
      answer:
        "I’d reproduce the contract check from the original specification and sandbox response. The report passes when the stated field type matches the observed evidence. Keep both review verdicts with their report revisions."
    ),
    Channel(
      id: "reliability", name: "Reliability & Operations", mandate: "Recovery and runtime health",
      question: "If a worker stops after dispatch, how do we avoid a duplicate ticket?",
      answer:
        "Look up the recorded intent and reconcile it with the ticket service using the original idempotency key. If the outcome is uncertain, keep the task blocked for operator review."
    ),
  ]
}
