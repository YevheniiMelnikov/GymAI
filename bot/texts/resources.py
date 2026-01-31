from enum import Enum, auto


class AutoName(str, Enum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name


class ButtonText(AutoName):
    female = auto()
    male = auto()

    quit = auto()
    done = auto()
    select = auto()
    prev_menu = auto()
    ask_ai = auto()
    ask_ai_again = auto()
    diets = auto()

    my_profile = auto()
    my_program = auto()
    top_up = auto()
    subscription_1_month = auto()
    subscription_6_months = auto()
    subscription_12_months = auto()

    faq = auto()

    beginner = auto()
    intermediate = auto()
    advanced = auto()
    experienced = auto()
    gym_workout = auto()
    home_workout = auto()

    view = auto()
    weekly_survey_answer = auto()

    answer_yes = auto()
    answer_no = auto()

    def __str__(self) -> str:
        return f"buttons.{self.name}"


class MessageText(AutoName):
    invalid_content = auto()
    unexpected_error = auto()
    coach_agent_error = auto()
    coach_agent_refund_note = auto()
    help = auto()

    default_status = auto()
    request_in_progress = auto()
    waiting_for_text = auto()
    choose_gender = auto()
    born_in = auto()
    workout_goals = auto()
    workout_location = auto()
    weight = auto()
    height = auto()
    workout_experience = auto()
    health_notes = auto()
    health_notes_question = auto()

    finish_registration = auto()
    weekly_survey_submitted = auto()

    profile_deleted = auto()
    your_data_updated = auto()
    select_language = auto()

    weekly_survey_prompt = auto()
    subscription_renewal_prompt = auto()

    payment_success = auto()
    payment_failure = auto()
    main_menu = auto()
    start = auto()
    saved = auto()
    ask_ai_response_template = auto()
    diet_ready = auto()

    ask_ai_prompt = auto()
    new_workout_plan = auto()
    program_updated = auto()

    credit_balance_menu = auto()
    not_enough_credits = auto()
    initial_credits_granted = auto()
    info = auto()

    def __str__(self) -> str:
        return f"messages.{self.name}"
