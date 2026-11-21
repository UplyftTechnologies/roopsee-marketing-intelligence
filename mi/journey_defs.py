"""The journeys shown on the Journeys tab: their steps, in order, and how each step is counted.

Mirrors the Shopper journeys tab of the admin analytics on roopsee.com (Purchase, Checkout, Login & sign-up, Skin quiz) and adds Search, Roop chat and
After the order. A person (or visit) "reached" a step when they did it, or any LATER step of the same journey: a saved address or a default payment
method can skip a click. The yes/no per step and visit is built by the rebuild (mi/journey_sql.py); the events that mean each step are listed there.
"""

# key -> label, the steps (step key, label) and the text of "How this is counted" (term, text)
JOURNEYS = {
    "purchase": {
        "label": "Purchase",
        "blurb": "From visiting the site to a paid order",
        "steps": [("visited", "Visited the site"), ("view_item", "Viewed a product"), ("add_to_cart", "Added to cart"), ("view_cart", "Opened the cart"),
                  ("checkout", "Began checkout"), ("pay_started", "Started paying"), ("purchase", "Purchased")],
        "how": [("Visited the site", "every person (or visit) shown, after the filters and hidden traffic."),
                ("Viewed a product", "opened a product page or a product detail."),
                ("Added to cart", "any add-to-cart button, Buy now, or a bundle add."),
                ("Opened the cart", "opened the cart drawer or the cart page."),
                ("Began checkout", "the checkout page opened or the cart's checkout button was tapped."),
                ("Started paying", "the pay button, payment started or the payment window opened."),
                ("Purchased", "a real order (not cancelled or pending, not a test), matched to its visit.")],
    },
    "checkout": {
        "label": "Checkout",
        "blurb": "From opening checkout to a confirmed order",
        "steps": [("opened", "Opened checkout"), ("logged_in", "Logged in"), ("address", "Address ready"), ("chose_pay", "Chose how to pay"), ("tapped_pay", "Tapped pay"),
                  ("ordered", "Order confirmed")],
        "how": [("Opened checkout", "the checkout page opened or the cart's checkout button was tapped."),
                ("Logged in", "the visit had an account, or logged in during it."),
                ("Address ready", "an address was picked, added or already saved."),
                ("Chose how to pay", "a payment method was tapped."),
                ("Tapped pay", "the pay or place-order button."),
                ("Order confirmed", "a real order matched to the visit.")],
    },
    "login": {
        "label": "Login & sign-up",
        "blurb": "From being asked to log in to an account",
        "steps": [("asked", "Asked to log in"), ("otp_sent", "Sent the OTP"), ("otp_entered", "Entered the OTP"), ("logged_in", "Logged in"), ("new_account", "Created an account")],
        "how": [("Asked to log in", "a login popup or page was shown, or a login button was tapped."),
                ("Sent / entered the OTP", "the Send OTP and Verify buttons. A Google sign-in counts through these steps."),
                ("Logged in", "a successful login, by phone OTP or Google."),
                ("Created an account", "the account was created within an hour of the login.")],
    },
    "quiz": {
        "label": "Skin quiz",
        "blurb": "From opening the quiz to an order",
        "steps": [("opened", "Opened the quiz"), ("started", "Answered a question"), ("finished", "Finished"), ("saved", "Saved to an account"), ("add_to_cart", "Added to cart after"),
                  ("ordered", "Ordered")],
        "how": [("Opened → answered → finished", "the skin quiz screens, in order."),
                ("Saved to an account", "finished while logged in."),
                ("Added to cart / ordered", "after finishing the quiz, in the same visit.")],
    },
    "search": {
        "label": "Search & discovery",
        "blurb": "From searching to an order",
        "steps": [("searched", "Searched"), ("results", "Got results"), ("clicked", "Clicked a result"), ("add_to_cart", "Added to cart"), ("ordered", "Ordered")],
        "how": [("Searched", "typed a search and ran it."),
                ("Got results", "at least one search found something."),
                ("Clicked a result", "tapped a product in the search results."),
                ("Added to cart / ordered", "a visit that searched, then did this.")],
    },
    "chat": {
        "label": "Roop chat",
        "blurb": "From opening Roop to an order",
        "steps": [("opened", "Opened Roop"), ("asked", "Asked a question"), ("answered", "Got an answer"), ("clicked", "Clicked a product"), ("add_to_cart", "Added to cart"),
                  ("ordered", "Ordered")],
        "how": [("Opened Roop", "opened the skin-care assistant."),
                ("Asked / got an answer", "sent a message; an answer that did not fail."),
                ("Clicked a product", "tapped a product in Roop's answer."),
                ("Added to cart / ordered", "a visit that asked Roop, then did this.")],
    },
}
JOURNEY_KEYS = list(JOURNEYS)
AFTER_ORDER = {
    "label": "After the order",
    "blurb": "From placing an order to delivery",
    "steps": [("placed", "Order placed"), ("picked_up", "Picked up"), ("out_for_delivery", "Out for delivery"), ("delivered", "Delivered")],
    "how": [("Order placed", "a real sale, by the day it was placed."),
            ("Picked up / out for delivery / delivered", "the times the rider and courier steps were recorded. A later step counts for the earlier ones."),
            ("Payment confirmed", "a confirmed online payment, or cash collected on delivery."),
            ("Stuck", "placed more than 48 hours ago and not delivered yet.")],
}


def column(journey: str, step: str) -> str:
    return f"{journey}_{step}"


def columns() -> list[str]:
    return [column(j, s) for j, d in JOURNEYS.items() for s, _ in d["steps"]]
