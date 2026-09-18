"""Frontend Portal profile page controller (CMP-001)."""
from user.service import get_profile, update_profile

SAVE_BUTTON_LABEL = "Submit"
SAVE_CONFIRMATION = "Profile updated"


def render_profile_page(user_id):
    profile = get_profile(user_id)
    return {
        "fields": profile,
        "save_button": SAVE_BUTTON_LABEL,
    }


def submit_profile_form(user_id, form_values):
    result = update_profile(user_id, form_values)
    return {"profile": result, "toast": SAVE_CONFIRMATION}
