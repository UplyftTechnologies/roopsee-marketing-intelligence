"""What counts as a pain point: the problems the site reports, the stages a shopper goes through, and the events that mean "tried" / "got through".

This mirrors the Pain points tab of the admin analytics on roopsee.com (backend/src/services/painPointAnalytics.js). Keep the two in step.
`soft` problems (asked for the OTP again, closed a form) explain why a visit got stuck but do not make it stuck on their own.
"""

STAGES = [  # key, tab label, "stuck" label
    ("login", "Log in", "Couldn't log in"),
    ("address", "Address", "Couldn't enter an address"),
    ("order", "Place order", "Couldn't place the order"),
    ("payment", "Payment", "Couldn't pay"),
    ("speed", "Speed & errors", "Slow or broken pages, then left"),
]
STAGE_LABEL = {k: (a, b) for k, a, b in STAGES}

# key, stage, label, event_name, form_error names (None = the event on its own), soft, detail kind
_P = []


def _add(key, stage, label, event, errors=None, soft=False, detail=None):
    _P.append((key, stage, label, event, tuple(errors) if errors else None, soft, detail))


_add("invalid_phone", "login", "Entered an invalid mobile number", "form_error", ["invalid_phone_number"])
_add("otp_send_failed", "login", "OTP couldn't be sent", "form_error", ["otp_send_failed", "otp_server_unreachable"], detail="message")
_add("wrong_otp", "login", "Wrong or incomplete OTP", "form_error", ["otp_verification_failed", "invalid_otp_length", "otp_backend_verification_failed"], detail="message")
_add("otp_timeout", "login", "OTP check timed out", "form_error", ["otp_verification_timeout"])
_add("google_failed", "login", "Google sign-in failed", "form_error", ["google_signin_failed"], detail="message")
_add("link_phone_failed", "login", "Couldn't link the mobile number", "form_error", ["link_phone_failed", "profile_sync_failed"], detail="message")
_add("resent_otp", "login", "Asked for the OTP again", "clicked_resend_otp", soft=True)
_add("login_back", "login", "Went back from the login page", "clicked_login_back", soft=True)
_add("address_missing", "address", "Tapped pay without an address", "address_missing")
_add("address_invalid", "address", "Address form had errors", "form_error", ["address_validation"], detail="message")
_add("address_save_failed", "address", "Address couldn't be saved", "address_save_failed", detail="message")
_add("address_not_serviceable", "address", "We don't deliver to that address", "address_not_serviceable")
_add("location_denied", "address", "Blocked location access", "location_denied")
_add("location_failed", "address", "Location couldn't be found", "location_failed")
_add("address_closed", "address", "Closed the address form", "clicked_address_modal_close", soft=True)
_add("login_missing", "order", "Tapped pay while logged out", "login_missing")
_add("price_failed", "order", "Price couldn't be calculated", "checkout_price_failed", detail="message")
_add("order_failed", "order", "Order couldn't be created", "order_failed", detail="stage_message")
_add("cart_empty", "order", "Cart was empty at checkout", "cart_empty")
_add("payment_failed", "payment", "Payment failed", "payment_failed", detail="payment")
_add("payment_cancelled", "payment", "Closed the payment window", "payment_cancelled")
_add("razorpay_open_failed", "payment", "Payment window didn't open", "razorpay_open_failed", detail="value")
_add("slow_page_load", "speed", "Page was slow to show (over 3 s)", "slow_page_load", detail="page")
_add("app_error", "speed", "Something on the page broke", "app_error", detail="error")
_add("api_failed", "speed", "A request to our server failed", "api_failed", detail="endpoint_status")
_add("slow_api", "speed", "A request took over 5 s", "slow_api", detail="endpoint")

PROBLEMS = _P
PROBLEM_LABEL = {p[0]: p[2] for p in PROBLEMS}
PROBLEM_STAGE = {p[0]: p[1] for p in PROBLEMS}
PROBLEM_EVENT = {p[0]: {"event": p[3], "error_names": list(p[4] or [])} for p in PROBLEMS}  # to open the Events tab on a problem
PROBLEM_EVENTS = sorted({p[3] for p in PROBLEMS})

# stage -> events that mean the shopper tried it / got through it / are a "retry" of it
TRIED = {
    "login": ["clicked_send_otp", "clicked_verify_otp", "clicked_google_signin"],
    "address": ["clicked_address_modal_open", "address_field_filled", "clicked_save_address", "clicked_change_address"],
    "order": ["clicked_pay_now"],
    "payment": ["payment_started", "razorpay_opened"],
}
DONE = {
    "login": ["otp_verified", "login_successful", "existing_user_login", "login_popup_logged_in"],
    "address": ["address_saved", "selected_saved_address"],
    "order": ["payment_started", "razorpay_opened", "order_placed", "payment_completed", "page_viewed_checkout_success"],
    "payment": ["order_placed", "payment_completed", "page_viewed_checkout_success"],
}
RETRY = {
    "login": ("clicked_send_otp", "clicked_resend_otp"),
    "address": ("clicked_save_address",),
    "order": ("clicked_pay_now",),
    "payment": ("payment_failed",),
}
RETRY_LABEL = {"login": "OTP requests", "address": "tries to save", "order": "taps on pay", "payment": "failed payment attempts"}
LOGIN_PAGE = ["page_viewed_login", "login_prompt_shown", "login_popup_shown", "clicked_login", "clicked_checkout_login", "clicked_my_cart_login_to_checkout"]
