# AI Support Employee — System Architecture

## 1. Overview

The AI Support Employee is an **Agentic AI customer support system** that behaves
like a virtual support employee. It receives a natural-language customer message,
understands the intent, routes it to a specialized agent, uses business tools to
read/write data, remembers conversation context, resolves simple issues
automatically, and escalates complex cases to a human.

## 2. Layered Architecture

```
+-------------------------------------------------------------+
|                         GUI Layer                           |
|                  Streamlit chat interface                   |
|        (chat, example prompts, details/metadata panel)      |
+----------------------------+--------------------------------+
                             | HTTP (requests)
+----------------------------v--------------------------------+
|                         API Layer                           |
|                    FastAPI (main.py)                        |
|   POST /support/chat  GET /orders  GET /complaints  DELETE  |
+----------------------------+--------------------------------+
                             | run_support_workflow()
+----------------------------v--------------------------------+
|                   Coordinator Layer                         |
|                LangGraph workflow (graph.py)                |
|   state: customer_id, message, memory, intent_result,       |
|          selected_agent, tool_result, final_response,       |
|          escalated                                          |
+----------------------------+--------------------------------+
                             |
+----------------------------v--------------------------------+
|                       Agent Layer                           |
|  Query Handler | Support Resolution | Complaint Handler |   |
|  Escalation Agent | Memory & Context Manager               |
+----------------------------+--------------------------------+
                             |
+----------------------------v--------------------------------+
|                        Tool Layer                           |
|  order_tool | product_tool | complaint_tool | memory_tool   |
+----------------------------+--------------------------------+
                             |
+----------------------------v--------------------------------+
|                        Data Layer                           |
|   orders.csv | products.csv | complaints.csv | memory.json  |
+-------------------------------------------------------------+

         Gemini (google-genai) is used by the agents for
         classification, reasoning, and response polishing.
```

## 3. LangGraph Workflow

```
START
  -> load_memory        (load prior context for the customer)
  -> query_handler      (Gemini intent + entity extraction; rule-based fallback)
  -> route_request      (conditional edge based on intent)
        |-- order_tracking / product_info -> support_resolution
        |-- complaint                     -> complaint_handler
        |-- escalation / unknown          -> escalation_agent
        |-- clarification / needs_info    -> clarification
  -> final_decision     (assemble structured SupportResponse)
  -> update_memory      (persist the interaction)
END
```

## 4. Agent Responsibilities

| Agent | Responsibility |
|-------|----------------|
| **Query Handler** | Classify intent, extract entities (order_id, product_id, urgency, wants_human), recover context from memory. |
| **Support Resolution** | Resolve order tracking and product info using tools; ask for clarification when data is missing. |
| **Complaint Handler** | Log complaints, check order status & history, apply escalation rules. |
| **Escalation Agent** | Decide when to hand off to a human and produce a ticket summary. |
| **Memory & Context Manager** | Load context before handling, persist the interaction after. |

## 5. Decision & Escalation Logic

A case is **resolved automatically** when the intent is clear and the required
data exists. The system **asks for clarification** when essential information
(e.g. an order ID) is missing. It **escalates** when:

- Gemini classification confidence < 0.6
- intent is `unknown`
- the customer has 2+ prior complaints (repeated issue)
- the related order status is `Delayed`
- urgency is high
- the customer explicitly asks for a human
- required data is unavailable

## 6. Data Integrity Rule

Gemini is used for **classification, reasoning, and response wording only**.
All factual data (orders, products, complaints) comes exclusively from the CSV
tools — the model is never allowed to invent business data. The system also
degrades gracefully: if no API key is set, a deterministic rule-based classifier
keeps the workflow fully functional.
