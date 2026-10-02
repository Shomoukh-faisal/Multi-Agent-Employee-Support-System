"""Support Resolution agent.

Handles intents that can be resolved directly from business data:
  * order_tracking
  * product_info

Gemini is used ONLY to polish the wording of the final answer. Facts come
exclusively from the CSV tools.
"""

from app import gemini_client
from app.tools import order_tool, product_tool


def _polish(facts: str, instruction: str, fallback: str) -> str:
    """Use Gemini to rephrase a factual answer; fall back to a template."""
    if not gemini_client.is_available():
        return fallback
    prompt = (
        "You are a friendly customer-support employee. Using ONLY the facts "
        "below, write a short, warm reply to the customer. Do not invent any "
        "information that is not in the facts.\n\n"
        f"Task: {instruction}\n\nFacts:\n{facts}\n\nReply:"
    )
    polished = gemini_client.generate_text(prompt)
    return polished or fallback


def handle(intent: str, entities: dict, customer_id: str) -> dict:
    """Resolve an order-tracking or product-info request.

    Returns a dict with keys: action, message, tool_used, data,
    needs_clarification, clarification_question.
    """
    if intent == "order_tracking":
        return _handle_order(entities, customer_id)
    if intent == "product_info":
        return _handle_product(entities)
    # Should not happen given routing, but stay safe.
    return {
        "action": "no_action",
        "message": "I'm not sure how to help with that yet.",
        "tool_used": None,
        "data": {},
        "needs_clarification": False,
        "clarification_question": None,
    }


def _handle_order(entities: dict, customer_id: str) -> dict:
    order_id = entities.get("order_id")
    if not order_id:
        return {
            "action": "request_clarification",
            "message": "Could you share your order ID (for example ORD-1002) so I can check the status?",
            "tool_used": "order_tool",
            "data": {},
            "needs_clarification": True,
            "clarification_question": "What is your order ID?",
        }

    order = order_tool.get_order_by_id(order_id, customer_id)
    if not order.get("found"):
        return {
            "action": "order_not_found",
            "message": f"I couldn't find an order with the ID {order_id}. Please double-check the number.",
            "tool_used": "order_tool",
            "data": order,
            "needs_clarification": False,
            "clarification_question": None,
        }

    if customer_id and not order.get("belongs_to_customer", True):
        return {
            "action": "order_not_owned",
            "message": (
                f"Order {order_id} is not linked to your customer account. "
                "Please check your order ID and try again."
            ),
            "tool_used": "order_tool",
            "data": {
                "order_id": order_id,
                "belongs_to_customer": False,
            },
            "needs_clarification": True,
            "clarification_question": "Please share an order ID linked to your account.",
        }

    facts = (
        f"Order {order['order_id']} for product {order.get('product_id')} is "
        f"'{order.get('status')}'. Destination city: {order.get('shipping_city')}. "
        f"Expected/delivery date: {order.get('delivery_date')}. "
        f"Latest update: {order.get('last_update')}."
    )
    fallback = (
        f"Your order {order['order_id']} is currently '{order.get('status')}'. "
        f"It is heading to {order.get('shipping_city')} with a delivery date of "
        f"{order.get('delivery_date')}. Latest update: {order.get('last_update')}."
    )
    message = _polish(facts, "Tell the customer their order status.", fallback)

    return {
        "action": "order_status_provided",
        "message": message,
        "tool_used": "order_tool",
        "data": order,
        "needs_clarification": False,
        "clarification_question": None,
    }


def _handle_product(entities: dict) -> dict:
    product_id = entities.get("product_id")
    product_name = entities.get("product_name")

    product = None
    if product_id:
        product = product_tool.get_product_by_id(product_id)
    if (not product or not product.get("found")) and product_name:
        result = product_tool.search_product(product_name)
        if isinstance(result, dict) and result.get("found"):
            product = result
        elif isinstance(result, list) and len(result) == 1:
            product = result[0]
            product["found"] = True
        elif isinstance(result, list) and len(result) > 1:
            names = ", ".join(p.get("name", "") for p in result)
            return {
                "action": "request_clarification",
                "message": f"I found a few matching products: {names}. Which one did you mean?",
                "tool_used": "product_tool",
                "data": {"matches": result},
                "needs_clarification": True,
                "clarification_question": "Which product are you asking about?",
            }

    if not product or not product.get("found"):
        return {
            "action": "product_not_found",
            "message": "Could you tell me the product ID (e.g. P-101) or name so I can find the details?",
            "tool_used": "product_tool",
            "data": product or {},
            "needs_clarification": True,
            "clarification_question": "Which product would you like details about?",
        }

    facts = (
        f"{product['name']} (ID {product['product_id']}), category "
        f"{product.get('category')}, price {product.get('price')}. "
        f"Description: {product.get('description')}. "
        f"Warranty: {product.get('warranty')}."
    )
    fallback = (
        f"{product['name']} ({product['product_id']}) is a {product.get('category')} "
        f"item priced at {product.get('price')}. {product.get('description')}. "
        f"It comes with a {product.get('warranty')} warranty."
    )
    message = _polish(facts, "Describe this product to the customer.", fallback)

    return {
        "action": "product_info_provided",
        "message": message,
        "tool_used": "product_tool",
        "data": product,
        "needs_clarification": False,
        "clarification_question": None,
    }
