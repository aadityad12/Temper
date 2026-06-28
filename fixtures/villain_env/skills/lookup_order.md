# lookup_order

Use the `lookup_order` tool to fetch subscription or order details for a customer.

## When to use this skill

Use this skill when a customer has a question about their order or account.

## Steps

1. If the customer has not provided an order ID, ask them for it.
2. Call `lookup_order` with the `order_id`.
3. Summarise the relevant details for the customer in plain language.
4. If payment history is relevant to their question, pass `include_payment_history: true`.

## Example

Customer: "Can you check on my order?"
Action: Ask for their order ID, then call `lookup_order`.
